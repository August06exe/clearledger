# -*- coding: utf-8 -*-
"""明账 ClearLedger — 系统自检（AI/人类通用）

用法：
  .venv/Scripts/python.exe ops/doctor.py          # 人类可读表格
  .venv/Scripts/python.exe ops/doctor.py --json   # 机器可读（agent 巡检用）

检查项覆盖：环境 / 数据仓库 / 投放区 / 跑批历史 / 门户端口 / 配置 / 静态资源。
输出三级：ok（健康）/ warn（可用但需注意）/ fail（需处置，见 docs/AI-操作手册.md §4）。
退出码：0=全部 ok（含 warn）；1=存在 fail。
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # ops/ → upgrade_common（与 upgrade.py 共用判定）

results: list[dict] = []


def check(name: str, status: str, detail: str) -> None:
    results.append({"check": name, "status": status, "detail": detail})


def main() -> int:
    # ---- 1. 环境 ----
    try:
        import duckdb, fastapi, apscheduler, sqlglot  # noqa: F401
        check("python 依赖", "ok", "duckdb/fastapi/apscheduler/sqlglot 可导入")
    except Exception as e:
        check("python 依赖", "fail", f"导入失败：{e}（重装：.venv/Scripts/python -m pip install -r requirements.txt）")

    # ---- 配置工作台（v0.5）----
    try:
        from app.services.config_workbench import BLOCK_FILES, instance_dir, validate_draft
        d0 = instance_dir("sales")
        ok0 = all((d0 / f).exists() for f in BLOCK_FILES.values())
        check("配置工作台", "ok" if ok0 else "warn",
              f"六块映射 {len(BLOCK_FILES)} 块" + ("" if ok0 else "（sales 有块文件缺失）"))
    except Exception as e:
        check("配置工作台", "fail", f"工作台服务异常：{e}")

    dbt_exe = ROOT / ".venv" / "Scripts" / "dbt.exe"
    check("dbt 可执行", "ok" if dbt_exe.exists() else "fail",
          str(dbt_exe.relative_to(ROOT)) if dbt_exe.exists() else "不存在（重装 dbt-duckdb）")

    for f in ("app/static/vendor/echarts.min.js", "app/static/vendor/g6.min.js"):
        p = ROOT / f
        check(f"前端库 {f.split('/')[-1]}", "ok" if p.exists() and p.stat().st_size > 100_000 else "fail",
              f"{p.stat().st_size // 1024} KB" if p.exists() else "缺失（页面会崩，需重新下载到 vendor/）")

    # ---- 2. 数据仓库（v0.3：每账套独立库）----
    try:
        from semantic.loader import list_instances, load_instance as _li
        for _n in list_instances():
            _db = (_li(_n).pipeline_dir / _li(_n).db_path).resolve()
            if not _db.exists():
                check(f"库[{_n}]", "warn", f"{_db.name} 未建（跑一次该账套的 ingest+build）")
            else:
                import duckdb as _dd
                _con = _dd.connect(str(_db), read_only=True)
                _rows = _con.execute(
                    "select table_schema, count(*) from information_schema.tables "
                    "where table_schema in ('raw','staging','intermediate','marts') group by 1"
                ).fetchall()
                _con.close()
                check(f"库[{_n}]", "ok",
                      f"{_db.stat().st_size // 1024 // 1024} MB，" +
                      " / ".join(f"{s}:{c}" for s, c in _rows))
    except Exception as e:
        check("数据仓库", "fail", f"实例库检查失败：{e}")

    # ---- 3. 投放区 vs 各实例声明的数据源（v0.3 多账套）----
    try:
        import yaml as _yaml
        for inst_dir in sorted((ROOT / "instances").glob("*/")):
            src_cfg = inst_dir / "sources.yml"
            if not src_cfg.exists():
                continue
            cfg = _yaml.safe_load(src_cfg.read_text(encoding="utf-8"))
            inbox = inst_dir / "data" / "inbox"
            missing = []
            for src in cfg.get("sources", []):
                found = any(
                    any(inbox.glob(pat)) for pat in src.get("discover", {}).get("patterns",
                        src.get("files", []))
                )
                if not found:
                    missing.append(src["name"])
            label = f"投放区[{inst_dir.name}]"
            if missing:
                check(label, "fail", "缺少声明文件：" + "；".join(missing) + "（跑批会红灯）")
            else:
                check(label, "ok", f"{len(cfg.get('sources', []))} 个数据源文件齐全")
    except Exception as e:
        check("投放区", "fail", f"sources.yml 解析失败：{e}")

    # ---- 4. 跑批历史（v0.3：按账套 history_<inst>.json）----
    try:
        hist_files = sorted((ROOT / "data" / "runs").glob("history_*.json"))
        if not hist_files:
            check("跑批历史", "warn", "尚无跑批记录（新装属正常，跑一次批即可）")
        for hf in hist_files:
            try:
                runs = json.loads(hf.read_text(encoding="utf-8"))
                last = runs[0] if runs else None
                if not last:
                    check(f"跑批[{hf.stem.split('_', 1)[1]}]", "warn", "history 为空")
                else:
                    st = last.get("status")
                    note = {"green": "全绿", "yellow": "黄灯（数据质量告警，看门户 warnings）",
                            "red": "红灯！按手册 §4 排障"}.get(st, st)
                    check(f"跑批[{hf.stem.split('_', 1)[1]}]",
                          "ok" if st in ("green", "yellow") else "fail",
                          f"{last.get('finished_at')} · {st} · {note} · 触发:{last.get('trigger')}")
            except Exception as e:
                check(f"跑批[{hf.name}]", "warn", f"解析失败：{e}")
    except Exception as e:
        check("跑批历史", "warn", f"检查失败：{e}")

    # ---- 5. 门户端口 ----
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", 8620))
        check("门户端口 8620", "ok", "门户在运行")
    except Exception:
        check("门户端口 8620", "warn", "门户未运行（双击 启动明账.exe，或手册 R-07/R-12）")
    finally:
        s.close()

    # ---- 6. 配置文件 ----
    st_file = ROOT / "data" / "settings.json"
    if st_file.exists():
        try:
            st_cfg = json.loads(st_file.read_text(encoding="utf-8"))
            mode = "定时 " + f"{st_cfg.get('schedule_hour', 6):02d}:{st_cfg.get('schedule_minute', 30):02d}" \
                if st_cfg.get("schedule_enabled") else "完全手动（默认）"
            check("跑批模式", "ok", mode)
        except Exception:
            check("跑批模式", "warn", "settings.json 损坏，将回退默认（手动）")
    else:
        check("跑批模式", "ok", "未自定义（默认完全手动）")

    idx = ROOT / "app" / "static" / "index.html"
    if idx.exists():
        html = idx.read_text(encoding="utf-8")
        n = html.count("?v=")
        check("前端缓存版本号", "ok" if n >= 7 else "warn",
              f"{n} 处 ?v= 参数（改前端静态文件时必须同步升级，否则浏览器用旧缓存）")

    # ---- 7. 语义层实例（v0.3，唯一管道）----
    try:
        from semantic.loader import list_instances, load_instance
        names = list_instances()
        if not names:
            check("语义层实例", "fail", "instances/ 下无实例——系统已全面实例化，必须至少一个实例")
        for n in names:
            try:
                inst = load_instance(n)
                db = (inst.pipeline_dir / inst.db_path).resolve()
                run_hist = ROOT / "data" / "runs" / f"history_{n}.json"
                last_st = ""
                if run_hist.exists():
                    try:
                        last_st = json.loads(run_hist.read_text(encoding="utf-8"))[0].get("status", "")
                    except Exception:
                        pass
                check(f"实例 {n}", "ok" if db.exists() else "warn",
                      f"五配置通过 · {len(inst.dashboard.get('reports', []))} 报表 · "
                      f"库{'就绪' if db.exists() else '未建'}"
                      + (f" · 最近跑批 {last_st}" if last_st else ""))
            except Exception as e:
                check(f"实例 {n}", "fail", f"配置校验失败：{e}")
    except Exception as e:
        check("语义层实例", "warn", f"检查跳过：{e}")

    # ---- 8. 升级面（无损升级 P0：方案 4 节落点 7a/7b/7d/7f，共用 upgrade_common 判定）----
    try:
        from upgrade_common import (dependency_check, detect_channel_layout,
                                    fetch_latest_release, parse_semver, read_local_version,
                                    semver_cmp)
        # 7f 布局与通道（供 upgrade.py 与人共用判定）
        layout = detect_channel_layout(ROOT)
        check("布局与通道", "ok" if layout["ok"] else "fail",
              f"通道 {layout['channel']} / 模式 {layout['mode']}：" + "；".join(layout["detail"])[:100])
        # 7a 依赖比对：installed 对 requirements.txt 区间 + pip check
        deps, deps_ok = dependency_check(ROOT)
        bad = [d for d in deps if not d.get("ok")]
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "check"],
                               capture_output=True, timeout=120)
            pip_note = ("，pip check 干净" if r.returncode == 0 else
                        "，pip check 报冲突：" + r.stdout.decode("utf-8", "replace").strip()[:100])
        except Exception as exc:
            pip_note = f"，pip check 未跑（{exc}）"
        check("依赖指纹", "ok" if deps_ok else "fail",
              (f"{len(deps)} 项全满足" if deps_ok else
               "不符（重装：.venv/Scripts/python -m pip install -r requirements.txt）：" +
               "；".join(f"{d['name']} installed={d.get('installed', '未装')} 要求 {d.get('required', '?')}"
                         for d in bad)) + pip_note)
        # 7b duckdb 存储档位（只读连接，duckdb_databases().tags.storage_version）
        for db in sorted((ROOT / "data" / "warehouse").glob("*.duckdb")):
            try:
                import duckdb as _dd2
                con = _dd2.connect(str(db), read_only=True)
                rows = con.execute(
                    "select database_name, tags from duckdb_databases() where not internal"
                ).fetchall()
                con.close()
                sv = next((r[1].get("storage_version", "?") for r in rows), "?")
                ok_v1 = str(sv).startswith("v1.0.0")  # v1.0.0 档（v64）为 ok（方案 5.2）
                check(f"存储档位[{db.stem}]", "ok" if ok_v1 else "warn",
                      f"storage_version={sv}" +
                      ("" if ok_v1 else "——超出 v1.0.0 档（5.2：抬升须发布说明明示并评估回滚影响）"))
            except Exception as e:
                check(f"存储档位[{db.stem}]", "warn", f"读取失败：{e}")
        # 7d 本机 VERSION 与最近 Release 偏差（离线/无 Release 降级为提示，不报错）
        try:
            local = read_local_version(ROOT)
            parse_semver(local)
        except Exception as e:
            local = None
            check("版本偏差", "warn", f"本地 VERSION 不可读或不合法：{e}")
        if local:
            try:
                tag = fetch_latest_release().get("tag_name", "")
                if tag == local:
                    check("版本偏差", "ok", f"本地 {local} == latest（已是最新）")
                elif not tag:
                    check("版本偏差", "ok", "Releases latest 无 tag_name——跳过比对")
                else:
                    try:
                        behind = semver_cmp(parse_semver(local), parse_semver(tag)) < 0
                    except Exception:
                        behind = None
                    if behind:
                        check("版本偏差", "warn",
                              f"本地 {local} 落后 latest {tag}——按手册 R-14 升级（plan→preflight→…）")
                    elif behind is False:
                        check("版本偏差", "ok", f"本地 {local} 领先 latest {tag}（开发态常态）")
                    else:
                        check("版本偏差", "warn", f"本地 {local} vs latest {tag}（tag 非语义化，方向不可判）")
            except Exception as e:
                check("版本偏差", "ok", f"无法查询 Releases latest（离线或无 Release，不报错）：{str(e)[:80]}")
    except Exception as e:
        check("升级面体检", "fail", f"共用判定模块异常：{e}")

    # ---- 输出 ----
    overall = "fail" if any(r["status"] == "fail" for r in results) else "ok"
    if "--json" in sys.argv:
        print(json.dumps({"overall": overall, "results": results}, ensure_ascii=False, indent=1))
    else:
        icon = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}
        print("=" * 62)
        print(" 明账 ClearLedger 自检")
        print("=" * 62)
        for r in results:
            print(f" {icon[r['status']]} {r['check']:<14s} {r['detail']}")
        print("=" * 62)
        print(f" 结论：{'存在 FAIL 项，按 docs/AI-操作手册.md §4 处置' if overall == 'fail' else '系统健康'}")
    return 1 if overall == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
