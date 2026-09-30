# -*- coding: utf-8 -*-
"""明账 ClearLedger — 统一备份工具（例行备份与升级快照共用同一实现）

设计规格：internal/docs/无损升级架构方案-20260930.md（4 节落点 8、3.3 步骤五）。
备份数据.bat 是本脚本的薄壳（保留双击习惯）；升级协议 ops/upgrade.py 的 backup
步骤同样调用本实现。三处入口，一份逻辑。

备份范围（例行与升级快照一致）：
  1. data/warehouse/*.duckdb 全部账套金库，连同同名 .wal；
  2. data/runs/ 整目录（跑批史，红绿灯审计资产）；
  3. logs/ 整目录；
  4. 各账套六份 yml（instance/sources/wide/dimensions/metrics/dashboard，红线一口径）；
  5. instances/<账套>/data/ 整目录（inbox 原始源文件——丢了不可再生，方案 2.3
     持久资产清单第一行；红队 B2 补入）；
  6. instances/<账套>/onboarding/config_history（配置工作台滚动备份）；
  7. data/openapi_keys.json、data/settings.json；
  8. VERSION 与 requirements.txt（升级前指纹，3.3 步骤五第 1 项）。

备份目录内布局镜像仓库相对路径（如 data/warehouse/sales.duckdb 原样落位），
恢复时按相对路径整树拷回即可。backup_manifest.json 记录每个文件三项指纹：
sha256 / size / mtime——sha256 供回滚恢复后的逐字节验收（3.3 步骤十情形 B），
size 加 mtime 供回滚情形判定的偏离探测（快）。每个 duckdb 复制后另以只读连接
体检一次可打开（沿 ops/doctor.py 的只读体检模式，占用时重试三次）。

命名：例行备份落 data/backup/<yyyyMMdd_HHmm>（同分钟重跑追加 -2 后缀，绝不
覆盖旧备份）；升级快照加 --tag <标记>，落 data/backup/<标记>-<yyyyMMdd_HHmm>
（协议传 pre-upgrade-<旧版>-<新版> 即得 3.3 规定的目录名）。

保留策略：本工具不自动删除任何备份。升级快照建议保留最近 3 份、例行备份最近
4 周——均为待人类拍板的建议值（方案开放问题 2），拍板前不做自动收敛。

一致性边界：升级协议里本步骤在 stop 之后执行（门户已停、无跑批），快照必然
一致；例行备份若恰逢跑批，duckdb 只读体检会因写锁失败而显式报错，不会静默
产出坏备份。

退出码：0=全部成功；1=有失败项（复制失败 / duckdb 体检不可读 / manifest 写盘
失败）；2=参数非法。输出人类可读中文行，--json 时末行追加机器可读完整清单。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 六份账套配置（与 app/services/config_workbench.py 的 BLOCK_FILES 同源：
# instance.yml + semantic/loader.py CONFIG_FILES 五份）
SIX_YML = ("instance.yml", "sources.yml", "wide.yml",
           "dimensions.yml", "metrics.yml", "dashboard.yml")

_CHUNK = 1024 * 1024
_TAG_RE = re.compile(r"^[A-Za-z0-9._-]+$")  # 禁分隔符——tag 直接进目录名，防穿越
_READOUT_RETRIES = 3  # 门户查询期间的短暂占用，沿语义层「只读+重试」纪律


def _utf8_stdio() -> None:
    """双击场景 bat 已 chcp 65001；管道/重定向下统一 UTF-8，输出可确定性解析。"""
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding and stream.encoding.lower().replace("-", "") != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M")


def _unique_dest(base: Path) -> Path:
    """同名目录已存在时追加 -2/-3 后缀——备份只增不覆盖。"""
    if not base.exists():
        return base
    n = 2
    while base.with_name(f"{base.name}-{n}").exists():
        n += 1
    return base.with_name(f"{base.name}-{n}")


def build_scope(root: Path) -> tuple[list[Path], list[dict]]:
    """展开备份范围：返回（待备份路径列表（文件或目录），跳过记录列表）。

    源不存在的可选项记入 skipped（信息性，不算失败）；warehouse 里一个
    duckdb 都没有才算致命（由调用方判定）。
    """
    items: list[Path] = []
    skipped: list[dict] = []

    def want(p: Path, missing_reason: str) -> None:
        if p.exists():
            items.append(p)
        else:
            skipped.append({"path": p.relative_to(root).as_posix(), "reason": missing_reason})

    # 1. 账套金库 + .wal（wal 名 = <库名>.wal，沿旧 bat 约定）
    for db in sorted((root / "data" / "warehouse").glob("*.duckdb")):
        items.append(db)
        wal = db.with_name(db.name + ".wal")
        if wal.exists():
            items.append(wal)

    # 2/3. 跑批史与日志
    want(root / "data" / "runs", "源不存在（尚无跑批史，新装属正常）")
    want(root / "logs", "源不存在")

    # 4/5. 各账套六份 yml + config_history（无 instance.yml 的目录不算账套）
    inst_root = root / "instances"
    if inst_root.is_dir():
        for inst in sorted(p for p in inst_root.iterdir() if p.is_dir()):
            if not (inst / "instance.yml").exists():
                continue
            for fname in SIX_YML:
                want(inst / fname, f"{inst.name} 账套缺 {fname}")
            want(inst / "data", f"{inst.name} 无 data/inbox（原始源文件丢了不可再生，2.3 持久资产清单）")
            want(inst / "onboarding" / "config_history",
                 f"{inst.name} 无 config_history（未用过配置工作台属正常）")

    # 6. 门户侧单文件
    want(root / "data" / "openapi_keys.json", "源不存在（尚未登记 API Key）")
    want(root / "data" / "settings.json", "源不存在（未自定义门户设置）")

    # 7. 升级前指纹（3.3 步骤五第 1 项把两者列入快照）
    want(root / "VERSION", "源不存在（版本单一出处缺失，本仓库应有此文件）")
    want(root / "requirements.txt", "源不存在")

    return items, skipped


def _copy_one(src: Path, dest_root: Path, root: Path,
              files: list[dict], failed: list[dict]) -> None:
    """单文件复制：复制流内计算 SHA256，记录 sha256/size/mtime 三项指纹。"""
    rel = src.relative_to(root)
    try:
        st = src.stat()  # 开读前取源指纹（mtime 记为开读时刻值）
        dst = dest_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        copied = 0
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while True:
                chunk = fsrc.read(_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                fdst.write(chunk)
                copied += len(chunk)
        if copied != st.st_size:
            raise IOError(f"复制期间源文件被改动（读 {copied} 字节，stat 记 {st.st_size}）")
        if dst.stat().st_size != copied:
            raise IOError(f"目标字节数不符（写 {dst.stat().st_size}，读 {copied}）")
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns))  # 备份件保留源 mtime
        files.append({"path": rel.as_posix(), "sha256": digest.hexdigest(),
                      "size": st.st_size, "mtime": st.st_mtime})
        print(f"  [OK] {rel.as_posix()}（{st.st_size:,} 字节）")
    except Exception as exc:
        failed.append({"path": rel.as_posix(), "error": str(exc)})
        print(f"  [失败] {rel.as_posix()}：{exc}")


def backup_item(src: Path, dest_root: Path, root: Path,
                files: list[dict], failed: list[dict]) -> None:
    """文件直接复制；目录递归展开（空目录也重建，保证整树可原样恢复）。"""
    if src.is_dir():
        for d, dirnames, filenames in os.walk(src):
            dirnames.sort()
            rel_d = Path(d).relative_to(root)
            (dest_root / rel_d).mkdir(parents=True, exist_ok=True)
            for fn in sorted(filenames):
                _copy_one(Path(d) / fn, dest_root, root, files, failed)
    else:
        _copy_one(src, dest_root, root, files, failed)


def check_duckdb_readable(dbs: list[Path], root: Path) -> tuple[list[dict], bool]:
    """每个金库只读连接执行一条 SELECT（沿 ops/doctor.py 只读体检模式）。"""
    results: list[dict] = []
    try:
        import duckdb
    except Exception as exc:
        return ([{"path": "<import>", "readable": False,
                  "detail": f"duckdb 模块导入失败：{exc}"}], False)
    for db in dbs:
        rec: dict = {"path": db.relative_to(root).as_posix()}
        ok, detail = False, ""
        for _ in range(_READOUT_RETRIES):
            try:
                con = duckdb.connect(str(db), read_only=True)
                rows = con.execute(
                    "select table_schema, count(*) from information_schema.tables "
                    "where table_schema in ('raw','staging','intermediate','marts') group by 1"
                ).fetchall()
                con.close()
                ok = True
                detail = " / ".join(f"{s}:{c}" for s, c in rows) or "空库（无分层表）"
                break
            except Exception as exc:
                detail = str(exc).splitlines()[0] if str(exc) else repr(exc)
                time.sleep(1)
        rec.update(readable=ok, detail=detail)
        print(f"  [{'OK' if ok else '失败'}] 只读体检 {rec['path']}：{detail}")
        results.append(rec)
    return results, all(r["readable"] for r in results)


def read_app_version(root: Path) -> str | None:
    try:
        return (root / "VERSION").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="明账 ClearLedger 统一备份（例行备份与升级快照共用同一实现）")
    parser.add_argument("--tag", help="升级快照标记：目录落 data/backup/<tag>-<时间戳>"
                                      "（协议传 pre-upgrade-<旧版>-<新版>）")
    parser.add_argument("--json", action="store_true", help="末行追加机器可读完整清单 JSON")
    parser.add_argument("--root", default=str(ROOT),
                        help="产品根（默认本脚本所在仓库根；首升场景由 upgrade.py 传入旧根）")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.tag and not _TAG_RE.match(args.tag):
        print(f"[明账] --tag 含非法字符（只允许字母数字 . _ -）：{args.tag}", file=sys.stderr)
        return 2

    kind = "upgrade-snapshot" if args.tag else "routine"
    label = f"升级快照[{args.tag}]" if args.tag else "例行备份"
    dest = _unique_dest(root / "data" / "backup" /
                        (f"{args.tag}-{_stamp()}" if args.tag else _stamp()))

    dbs = sorted((root / "data" / "warehouse").glob("*.duckdb"))
    if not dbs:
        print("[明账] 备份失败：data/warehouse/ 下找不到任何账套金库（*.duckdb）")
        return 1

    items, skipped = build_scope(root)
    print(f"[明账] {label} → {dest.relative_to(root).as_posix()}"
          f"（范围 {len(items)} 项，跳过 {len(skipped)} 项）")
    dest.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    files: list[dict] = []
    failed: list[dict] = []
    for item in items:
        backup_item(item, dest, root, files, failed)
    for s in skipped:
        print(f"  [跳过] {s['path']}（{s['reason']}）")

    db_results, db_all_ok = check_duckdb_readable(dbs, root)

    manifest = {
        "format": "clearledger-backup-manifest/1",
        "kind": kind,
        "tag": args.tag,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": str(root),
        "app_version": read_app_version(root),
        "dest": dest.name,
        "files": files,
        "skipped": skipped,
        "failed": failed,
        "duckdb_check": db_results,
        "totals": {"files": len(files),
                   "bytes": sum(f["size"] for f in files),
                   "failed": len(failed),
                   "elapsed_seconds": round(time.monotonic() - started, 1)},
    }
    manifest_path = dest / "backup_manifest.json"
    try:
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as exc:
        print(f"[明账] 备份失败：清单写盘失败 {manifest_path}：{exc}")
        return 1

    ok = not failed and db_all_ok
    mb = manifest["totals"]["bytes"] / 1024 / 1024
    print(f"[明账] {'备份完成' if ok else '备份有失败项！'}：{dest.relative_to(root).as_posix()}"
          f"（{len(files)} 个文件，{mb:.1f} MB，失败 {len(failed)}"
          f"+金库体检{'全过' if db_all_ok else '未过'}，"
          f"耗时 {manifest['totals']['elapsed_seconds']}s）")
    print(f"[明账] 清单：{manifest_path.relative_to(root).as_posix()}"
          f"（每条含 sha256/size/mtime；恢复按相对路径整树拷回）")
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
