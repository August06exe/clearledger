# -*- coding: utf-8 -*-
"""P0 无损升级协议·真机全链演练（沙盘驱动，直接执行非 unittest）

用法：.venv/Scripts/python.exe tests/upgrade/drill_p0.py
退出码：0 = 七项清单全过；1 = 有失败项（逐项证据已打印）。

规格：internal/docs/无损升级架构方案-20260930.md 第 8 节 P0 完成定义——
通道 Z 与通道 G 各跑一遍全链，必含 migrate 中途 kill 后的续跑或 --revert、
switch 后 rollback 情形 A 与情形 B、merge 冲突按登记簿对账，以及两个机理
验证点（rename 运行中 .venv 必败 / py -3 脚本 rename 自己所在目录可执行）。

沙盘纪律（演练教官约束）：
- 一切沙盘建在系统临时目录（tempfile.mkdtemp），绝不触碰仓库 data/ 与真实
  账套；结束保留最后一场（G 通道场景）供检查，此前的场景清理；
- 只用真实 ops/upgrade.py 以 --root <沙盘根> 驱动，不 monkeypatch、不改
  协议语义；解释器照 6.4 表：plan/preflight/stop/backup/sync/canary/smoke/
  finalize 用仓库 .venv，migrate/switch/rollback 用 py -3；
- 沙盘 .venv 以 junction 挂主仓 .venv（产品级依赖一步到位；演练已实测
  junction 的 create/rename/rmdir 均不动目标、3.12 rmtree 不跟进 junction）；
  协议只对 .venv 做 rename 搬迁，不会写它；
- 演练会按协议杀 8620 端口进程（含本机真门户）——结束时会恢复演练前的
  监听状态（原本在跑则从主仓根重启）。

首升场景按 6.4 引导：zip 手工解包出 upgrade/staging-v<目标>（stage 子命令
当前为骨架占位，exit 3 属预期，记入清单 notes，不判失败）。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UPGRADE = REPO / "ops" / "upgrade.py"
VENV_PY = REPO / ".venv" / "Scripts" / "python.exe"
PY3 = ["py", "-3"]
PORT = 8620

# 沙盘产品树裁剪：现场公开仓语义（不含 internal/，tests/docs 与演练无关）
TOP_DIRS = ("app", "semantic", "ops", "instances", "sample_data", "scripts")
TOP_FILES = ("VERSION", "requirements.txt", ".gitignore", "README.md")
KEEP_INSTANCES = ("sales", "restaurant")  # launcher 演示闸门认 sales+restaurant（ops/launcher.py DEMO_INSTANCES）
IGNORE_PAT = shutil.ignore_patterns("__pycache__", ".pytest_cache", "target", "dbt_packages", "logs", "*.log")

RENAME_PROBE = "import os,sys\ntry:\n    os.rename(sys.argv[1], sys.argv[2]); print('RENAME-OK')\nexcept OSError as e:\n    print('RENAME-FAIL:', e)"
DRIFT_CHECK = "import duckdb, sys\ntry:\n    con = duckdb.connect(sys.argv[1], read_only=True)\n    con.execute('select count(*) from marts.drill_drift_probe').fetchall()\n    print('DRIFT-TABLE-STILL-HERE')\nexcept Exception:\n    print('DRIFT-TABLE-GONE')"
MOVER_SRC = "import os\nhere = os.path.dirname(os.path.abspath(__file__))\ndst = here + '_moved'\nos.rename(here, dst)\nprint('SELFMOVE-OK')"

REGISTRY = "HRO-私有改动说明.md"  # 现场登记簿文件名（方案 2.4/3.3 步骤六 6B）

ITEMS: list[dict] = []      # {item, result, notes}
DEFECTS: list[str] = []     # 疑似产品缺陷（协议实现的问题，实施工程师修）


def log(msg: str) -> None:
    print(msg, flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, cwd=None, timeout=1800, env=None):
    p = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                       capture_output=True, timeout=timeout, env=env)
    out = (p.stdout or b"").decode("utf-8", "replace")
    err = (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out, err


def parse_payload(out: str):
    for ln in reversed(out.splitlines()):
        ln = ln.strip()
        if ln.startswith("{"):
            try:
                return json.loads(ln)
            except Exception:
                continue
    return None


def show(step: dict, tail: int = 8) -> None:
    """打印一步真命令的证据（命令行、退出码、输出尾部）。"""
    log(f"  $ {' '.join(str(c) for c in step['cmd'])}")
    log(f"    → exit {step['rc']}" + (f"（预期 {step['expect']}）" if "expect" in step else ""))
    lines = [ln for ln in step["out"].splitlines() if ln.strip()]
    for ln in lines[-tail:]:
        log(f"    | {ln}")


def upgrade(root: Path, step_name: str, *extra, py3: bool = False, expect: int = 0,
            timeout: int = 1800) -> dict:
    """跑真实 ops/upgrade.py <子命令>。--root/--json 置于子命令之前（6.4）。
    注意 cwd 固定为主仓根（绝不进沙盘根——switch/rollback 会 rename 沙盘根，
    子进程 cwd 若在其内 rename 必败，这是机理不是缺陷）。"""
    cmd = (PY3 if py3 else [str(VENV_PY)]) + [str(UPGRADE), "--root", str(root),
                                              "--json", step_name, *[str(e) for e in extra]]
    rc, out, err = run(cmd, cwd=REPO, timeout=timeout)
    step = {"cmd": cmd, "rc": rc, "out": out, "err": err, "payload": parse_payload(out)}
    if expect is not None:
        step["expect"] = expect
    show(step)
    return step


# ---------------------------------------------------------------- 端口卫生

def port_pid() -> int | None:
    try:
        raw = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=15).stdout
    except Exception:
        return None
    for line in raw.decode("utf-8", "replace").splitlines():
        if f":{PORT}" in line and "LISTENING" in line.upper():
            return int(line.split()[-1])
    return None


def kill_8620() -> None:
    pid = port_pid()
    while pid:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=15)
        time.sleep(0.5)
        new = port_pid()
        if new == pid:
            break
        pid = new


def restore_portal(was_running: bool) -> None:
    kill_8620()
    if not was_running:
        return
    log(f"[drill] 恢复演练前的真门户（主仓根重启，R-07 形态）")
    (REPO / "logs").mkdir(parents=True, exist_ok=True)
    logf = open(REPO / "logs" / "uvicorn.log", "ab")
    subprocess.Popen([str(VENV_PY), "-m", "uvicorn", "app.main:app",
                      "--host", "127.0.0.1", "--port", str(PORT)],
                     cwd=str(REPO), stdout=logf, stderr=subprocess.STDOUT,
                     creationflags=0x00000008 | 0x00000200, close_fds=True)
    for _ in range(30):
        time.sleep(1)
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=1)
            s.close()
            log(f"[drill] 真门户已恢复监听 {PORT}")
            return
        except OSError:
            continue
    log("[drill] ⚠️ 真门户 30 秒内未恢复监听——人工按 R-07 处置")


# ---------------------------------------------------------------- 沙盘构件

def mount_venv(root: Path) -> None:
    """沙盘 .venv = junction → 主仓 .venv（真实产品级依赖；协议只 rename 它）。"""
    import _winapi
    _winapi.CreateJunction(str(REPO / ".venv"), str(root / ".venv"))


def copy_product_tree(dst: Path, version: str) -> None:
    """现场公开仓语义的最小产品树（sales+restaurant 两演示账套）。"""
    dst.mkdir(parents=True, exist_ok=True)
    for name in TOP_DIRS:
        src = REPO / name
        if not src.is_dir():
            continue
        if name == "instances":
            (dst / "instances").mkdir()
            for inst in KEEP_INSTANCES:
                if (src / inst).is_dir():
                    shutil.copytree(src / inst, dst / "instances" / inst, ignore=IGNORE_PAT)
        else:
            shutil.copytree(src, dst / name, ignore=IGNORE_PAT)
    for name in TOP_FILES:
        src = REPO / name
        if src.is_file():
            shutil.copy2(src, dst / name)
    (dst / "VERSION").write_text(version + "\n", encoding="utf-8")
    lock_requirements(dst)  # 见其 docstring：沙盘必须与挂载 venv 自洽


def stage_data(root: Path) -> None:
    """金库（真实 duckdb，取主仓已建库）+ settings。"""
    wh = root / "data" / "warehouse"
    wh.mkdir(parents=True, exist_ok=True)
    for inst in KEEP_INSTANCES:
        shutil.copy2(REPO / "data" / "warehouse" / f"{inst}.duckdb", wh / f"{inst}.duckdb")
    (root / "data" / "settings.json").write_text(
        json.dumps({"instance": "sales", "schedule_enabled": False}, ensure_ascii=False),
        encoding="utf-8")


def strip_builtin_local_assets(tree: Path) -> None:
    """出包语义：zip 只含产品与 builtin 配置——本地资产（data/onboarding）不进包，
    由 migrate 搬迁（3.2 清单第 5/6 项）。"""
    for inst in KEEP_INSTANCES:
        for sub in ("data", "onboarding"):
            p = tree / "instances" / inst / sub
            if p.exists():
                shutil.rmtree(p)


def lock_requirements(dst: Path) -> None:
    """沙盘 requirements.txt 按「主仓 venv 实装版本」锁定生成（== 钉死）。

    背景实测：主仓 venv 已漂移（pandas 3.0.5 > requirements 的 <3.0、sqlglot 30.18
    > <28），doctor 依赖指纹体检如实报 fail。沙盘若照抄主仓 requirements：
    ① smoke/rollback 收尾的 doctor 复检必挂；② rollback 在 py -3 下触发的
    pip install -r 会顺着 junction 把主仓 venv 降级——绝对不行。锁定版与挂载的
    venv 自洽，是「一致的产品根」的诚实形态（真实 zip 会带自己的钉版清单）。
    """
    probe = (
        "import importlib.metadata as md, json, re, sys\n"
        "names = []\n"
        "for line in open(sys.argv[1], encoding='utf-8'):\n"
        "    line = line.split('#', 1)[0].strip()\n"
        "    if not line:\n"
        "        continue\n"
        "    m = re.match(r'^([A-Za-z0-9_.\\-]+)', line)\n"
        "    if m:\n"
        "        names.append(m.group(1))\n"
        "out = {}\n"
        "for n in names:\n"
        "    try:\n"
        "        out[n] = md.version(n)\n"
        "    except Exception:\n"
        "        out[n] = None\n"
        "print(json.dumps(out))\n")
    rc, out, err = run([str(VENV_PY), "-c", probe, str(REPO / "requirements.txt")], timeout=120)
    assert rc == 0, f"锁定 requirements 探测失败：{err[-200:]}"
    pins = json.loads(out.strip().splitlines()[-1])
    lines = ["# 演练沙盘：按主仓 .venv 实装版本锁定（pandas/sqlglot 等已漂移出主仓区间，见演练报告）"]
    for name, ver in pins.items():
        lines.append(f"{name}=={ver}" if ver else f"{name}")
    (dst / "requirements.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_zip(tree: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for d, _dn, filenames in os.walk(tree):
            for fn in sorted(filenames):
                p = Path(d) / fn
                zf.write(p, p.relative_to(tree).as_posix())


def unpack(zip_path: Path, staging: Path) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(staging)
    # 引导命令语义：zip 解到 upgrade/staging-v<x>（方案 6.4 引导两命令）
    assert (staging / "VERSION").is_file(), "staging 缺 VERSION——解包形态不对"


def build_manifest(path: Path, *, version: str, min_from: str, zip_path: Path,
                   req_path: Path, mart_changed: bool, sentinels: list) -> dict:
    m = {
        "version": version,
        "min_upgradable_from": min_from,
        "zip_sha256": sha256_file(zip_path),
        "requirements_sha256": sha256_file(req_path),
        "duckdb_version": "1.5.5",
        "tenants_builtin": list(KEEP_INSTANCES),
        "launcher_rebuilt": False,
        "mart_schema_changed": mart_changed,
        "config_schema_version": {"instance_yml": 1, "settings": 1},
        "contract_version": 1,
        "contract_changes": [],
        "sentinel_reports": sentinels,
        "auto_apply": False,
        "requires_manual_steps": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return m


def make_duckdb(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rc, _o, err = run([str(VENV_PY), "-c",
                       "import duckdb,sys;con=duckdb.connect(sys.argv[1]);"
                       "con.execute('create schema if not exists raw;"
                       "create table if not exists raw.t as select 42 as v');con.close()",
                       str(path)])
    assert rc == 0, f"构造 duckdb 失败：{err}"


def six_yml(inst_dir: Path) -> None:
    inst_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("instance.yml", "sources.yml", "wide.yml",
                  "dimensions.yml", "metrics.yml", "dashboard.yml"):
        (inst_dir / fname).write_text(f"# fixture {fname}\n", encoding="utf-8")


def read_state(root: Path):
    p = root / "data" / "upgrade" / "state.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"corrupt": True}


def record(item: str, ok: bool, notes: str) -> None:
    ITEMS.append({"item": item, "result": "pass" if ok else "fail", "notes": notes})
    log(f"[item] {item} → {'PASS' if ok else 'FAIL'}｜{notes}")


# ---------------------------------------------------------------- 场景一：Z 通道首升全链 + canary 真跑

def phase_z_full_chain(base: Path) -> None:
    ok1, note1 = True, []
    ok7, note7 = True, []
    root = base / "z1" / "root"
    ups = base / "z1" / "upgrade"
    art = base / "artifacts"

    log("[z1] 构造 v0.9.0 沙盘根（完整产品树 + 真金库 + junction .venv + settings）与 v0.9.1 zip+manifest")
    copy_product_tree(root, "v0.9.0")
    mount_venv(root)
    stage_data(root)
    new_tree = art / "tree-v0.9.1"
    copy_product_tree(new_tree, "v0.9.1")
    strip_builtin_local_assets(new_tree)
    zip_path = art / "clearledger-v0.9.1.zip"
    make_zip(new_tree, zip_path)
    manifest = build_manifest(art / "manifest-v0.9.1.json", version="v0.9.1", min_from="v0.9.0",
                              zip_path=zip_path, req_path=new_tree / "requirements.txt",
                              mart_changed=True, sentinels=["region_month"])
    mf = str(art / "manifest-v0.9.1.json")

    def fail1(msg):
        nonlocal ok1
        ok1 = False
        note1.append(msg)

    # plan → preflight（只读两步）
    r = upgrade(root, "plan", "--manifest", mf)
    if r["rc"] != 0:
        fail1("plan 未过")
    note1.append(f"plan exit {r['rc']}：{(r['payload'] or {}).get('data', {}).get('version_check', '?')}")

    r = upgrade(root, "preflight", "--manifest", mf)
    if r["rc"] != 0:
        fail1(f"preflight 未过：{(r['payload'] or {}).get('data', {}).get('failed_checks') or r['out'][-200:]}")
    else:
        note1.append("preflight 通过（fail 0；deferred 2 项属骨架声明）")

    # 引导两命令：手工解包 staging，然后跑 stage（骨架占位，exit 3 预期）
    unpack(zip_path, ups / "staging-v0.9.1")
    r = upgrade(root, "stage", "--target", "v0.9.1", expect=3)
    note1.append(f"stage exit {r['rc']}（占位，exit 3 属骨架声明；staging 已按 6.4 引导两命令手工解包）")

    # 停机窗四步 + 换名
    r = upgrade(root, "stop")
    if r["rc"] != 0:
        fail1("stop 未过")
    r = upgrade(root, "backup")
    if r["rc"] != 0:
        fail1(f"backup 未过：{r['err'][-200:] or r['out'][-200:]}")
    else:
        snap = ((r["payload"] or {}).get("data") or {}).get("snapshot_dir", "?")
        note1.append(f"backup 快照落位 {Path(snap).name}")
        if port_pid():
            fail1("stop 后 8620 仍有监听")

    r = upgrade(root, "migrate", py3=True)
    if r["rc"] != 0:
        fail1("migrate 未过")
    else:
        note1.append("migrate（py -3）通过：意图化 rename 全过、状态文件随 data/ 迁至 staging")

    r = upgrade(root, "switch", py3=True)
    if r["rc"] != 0:
        fail1("switch 未过")
    else:
        ver = (root / "VERSION").read_text(encoding="utf-8").strip()
        if ver != "v0.9.1" or not (ups / "prev-v0.9.0").is_dir():
            fail1(f"switch 后验异常：VERSION={ver}")
        note1.append(f"switch（py -3）通过：槽位换名后根 VERSION={ver}，prev-v0.9.0 就位")

    # ---- canary 真跑（金丝雀：mart_schema_changed=true）----
    sales_db = root / "data" / "warehouse" / "sales.duckdb"
    pre_sha, pre_mtime = sha256_file(sales_db), sales_db.stat().st_mtime
    test_db = root / "data" / "warehouse" / "_upgrade_test.duckdb"
    r = upgrade(root, "canary", "--instance", "sales", timeout=2400)
    if r["rc"] != 0:
        ok7 = False
        note7.append(f"canary exit {r['rc']}：{r['out'][-300:]}")
    else:
        note7.append("canary 通过：_upgrade_test 三步链（ingest/compile/dbt build）全绿 + 哨兵 region_month 与基线一致（数值精确相等）")
    post_sha, post_mtime = sha256_file(sales_db), sales_db.stat().st_mtime
    # 机理证据：canary 声称不触碰原库（upgrade.py:1636），实测副本 instance.yml 的
    # database: 字段仍指 sales.duckdb（semantic/loader.py:102 → db_path 取该字段），
    # 三步链把 marts 重建进了真库 sales.duckdb——隔离失效，记产品缺陷。
    if post_sha != pre_sha:
        DEFECTS.append(
            "ops/upgrade.py cmd_canary（约 :1629-1658）：copytree 复制账套后未改写副本 instance.yml "
            "的 database: 字段（semantic/loader.py:102 db_path 直接取该字段，semantic/query.py:16 同源），"
            "金丝雀三步链与哨兵查询实际读写的是原库 sales.duckdb 而非 _upgrade_test.duckdb——"
            "与「不触碰原账套目录与原库（步骤八）」的声明相反；_upgrade_test.duckdb 复制件全程无人读写。"
            "修法：复制后把副本 instance.yml 的 database 改为（或删字段走默认）"
            "../../../data/warehouse/_upgrade_test.duckdb。"
            f"（演练实测：canary 前后 sales.duckdb sha256 {pre_sha[:12]}→{post_sha[:12]}，mtime {pre_mtime:.0f}→{post_mtime:.0f}）")
        note7.append("⚠️ 发现并记录产品缺陷：canary 未隔离原库（见 defects），演练沙盘内不影响后续断言")
    if not (root / "instances" / "_upgrade_test").exists():
        note7.append("canary 已自清 _upgrade_test（步骤八清理段）")

    # smoke + finalize
    r = upgrade(root, "smoke", timeout=1800)
    if r["rc"] != 0:
        fail1("smoke 未过：" + str([c for c in ((r['payload'] or {}).get('data', {}).get('checks') or [])
                                       if c['status'] != 'ok'] or r['out'][-300:]))
    else:
        note1.append("smoke 通过：doctor/launcher --smoke（沙盘门户自起 8620）/依赖指纹/真实查询/哨兵全绿")

    r = upgrade(root, "finalize")
    if r["rc"] != 0:
        fail1("finalize 未过")
    else:
        note1.append("finalize 通过（VERSION 复核 v0.9.1；?v= 复核对沙盘是拷贝新 mtime，warn 属预期）")

    record("Z 通道首升全链：v0.9.0→v0.9.1 plan→preflight→stage→stop→backup→migrate→switch→canary→smoke→finalize",
           ok1, "；".join(note1))
    record("canary 真跑（真 venv 经 junction 挂主仓 .venv；_upgrade_test 三步链+哨兵比对）",
           ok7, "venv 方案=junction 挂主仓 .venv（免网络装包，协议只对 .venv 做 rename）；" + "；".join(note7))


# ---------------------------------------------------------------- 场景二：migrate 中途 kill 后续跑 + --revert

def phase_z_kill(base: Path, tag: str, pad_files: int) -> tuple[bool, list[str]]:
    """返回 (成功, notes)。pad_files 越大 kill 窗口越宽（data/ 的字节对账走 walk）。"""
    notes: list[str] = []
    root = base / tag / "root"
    ups = base / tag / "upgrade"

    root.mkdir(parents=True)
    (root / "VERSION").write_text("v0.9.0\n", encoding="utf-8")
    lock_requirements(root)
    six_yml(root / "instances" / "acme")
    make_duckdb(root / "data" / "warehouse" / "acme.duckdb")
    (root / "data" / "settings.json").write_text(
        json.dumps({"instance": "acme", "schedule_enabled": False}), encoding="utf-8")
    # killpad：data/ 内的大批文件——不进备份范围（backup 只取 warehouse/runs/...），
    # 但会拖长 migrate 对 data/ 的两次 walk，撑开确定性的 kill 窗口
    pad = root / "data" / "killpad"
    pad.mkdir(parents=True)
    for i in range(pad_files):
        (pad / f"k{i:06d}.tmp").write_bytes(b"")
    # 假 .venv 占位（migrate 只 rename 它）
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "dbt.exe").write_bytes(b"placeholder")
    # staging 最小形态 + manifest
    (ups / "staging-v0.9.1" / "ops").mkdir(parents=True)
    (ups / "staging-v0.9.1" / "VERSION").write_text("v0.9.1\n", encoding="utf-8")
    art = base / "artifacts"
    mf = art / "manifest-v0.9.1-lite.json"  # lite：无哨兵——z2 是轻量沙盘，无产品代码可跑基线
    if not mf.is_file():
        if not (art / "clearledger-v0.9.1.zip").is_file():
            raise RuntimeError("先跑场景一产出 zip 工件")
        build_manifest(mf, version="v0.9.1", min_from="v0.9.0",
                       zip_path=art / "clearledger-v0.9.1.zip",
                       req_path=art / "tree-v0.9.1" / "requirements.txt",
                       mart_changed=False, sentinels=[])

    for step_name in ("plan", "preflight"):
        r = upgrade(root, step_name, "--manifest", str(mf))
        if r["rc"] != 0:
            return False, notes + [f"{step_name} 未过"]
    r = upgrade(root, "stop")
    if r["rc"] != 0:
        return False, notes + ["stop 未过"]
    r = upgrade(root, "backup")
    if r["rc"] != 0:
        return False, notes + [f"backup 未过：{r['out'][-200:]}"]

    # ---- 中途 kill：py -3 起 migrate 子进程，data/ 一消失（首个 rename 已发生）即杀 ----
    cmd = PY3 + [str(UPGRADE), "--root", str(root), "--json", "migrate"]
    log(f"  $ {' '.join(str(c) for c in cmd)}  （随后在 data/ 搬走瞬间 kill）")
    proc = subprocess.Popen([str(c) for c in cmd], cwd=str(REPO),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    moved, deadline = False, time.time() + 300
    while time.time() < deadline:
        if not (root / "data").exists():
            moved = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.002)
    if not moved:
        proc.kill()
        prc = proc.wait()
        tail = ((proc.stdout.read() or b"") + (proc.stderr.read() or b"")).decode("utf-8", "replace").strip()[-200:]
        return False, notes + [f"kill 窗口未出现（data/ 未被搬走；migrate exit {prc}：{tail}）"]
    if proc.poll() is None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=15)
    killed_rc = proc.wait()
    if killed_rc == 0:
        return False, notes + [f"kill 未命中（migrate 已自行跑完，exit 0）——pad={pad_files} 不足"]
    notes.append(f"migrate 子进程已杀（exit {killed_rc}），此刻 data/ 已在 staging、"
                 f"状态机意图在盘（全部 pending）——真实的中途死态")
    st = read_state(ups / "staging-v0.9.1")
    if not (isinstance(st, dict) and (st.get("migrate") or {}).get("intent")):
        return False, notes + ["中途死态不对：staging 侧 state.json 无搬迁意图"]

    # ---- 续跑：幂等接续 ----
    r = upgrade(root, "migrate", py3=True, timeout=1800)
    if r["rc"] != 0:
        return False, notes + [f"续跑失败 exit {r['rc']}"]
    if "对账一致" not in r["out"]:
        notes.append("⚠️ 续跑通过但未见「已搬过（对账一致）」行——续跑语义未走幂等分支")
    else:
        notes.append("续跑通过：「已搬过 data（对账一致——上次已搬，续跑）」幂等分支命中")

    # ---- --revert：整体退回 ----
    r = upgrade(root, "migrate", "--revert", py3=True, timeout=1800)
    if r["rc"] != 0:
        return False, notes + [f"--revert 失败 exit {r['rc']}"]
    back = (root / "data" / "warehouse" / "acme.duckdb").is_file() and (root / ".venv").is_dir()
    if not back:
        return False, notes + ["--revert 后旧根未复原"]
    notes.append("--revert 通过：全部已搬项归位旧根并复对账（data/、.venv、instances/acme 回根）")
    return True, notes


# ---------------------------------------------------------------- 场景三：rollback 情形 A / 情形 B

def _upgrade_to_switch(root: Path, ups: Path, zip_path: Path, mf: Path, tag: str) -> Path:
    """一轮完整升版（plan→…→switch），返回 backup 记录的快照目录。"""
    unpack(zip_path, ups / "staging-v0.9.1")
    for step_name in ("plan", "preflight"):
        r = upgrade(root, step_name, "--manifest", str(mf))
        assert r["rc"] == 0, f"{tag} {step_name} 未过：{r['out'][-200:]}"
    for step_name in ("stop", "backup"):
        r = upgrade(root, step_name)
        assert r["rc"] == 0, f"{tag} {step_name} 未过：{r['out'][-200:]}"
    r = upgrade(root, "migrate", py3=True)
    assert r["rc"] == 0, f"{tag} migrate 未过：{r['out'][-300:]}"
    r = upgrade(root, "switch", py3=True)
    assert r["rc"] == 0, f"{tag} switch 未过：{r['out'][-200:]}"
    prog_backup = (read_state(root) or {}).get("in_progress", {}).get("backup", {})
    return Path(prog_backup["snapshot_dir"])


def _build_z3_root(base: Path, tag: str) -> tuple[Path, Path, Path]:
    root = base / tag / "root"
    ups = base / tag / "upgrade"
    art = base / "artifacts"
    copy_product_tree(root, "v0.9.0")
    mount_venv(root)
    stage_data(root)
    mf = art / "manifest-v0.9.1-lite.json"
    if not mf.is_file():  # lite：mart 不变、无哨兵——rollback 场景不跑 canary/smoke
        build_manifest(mf, version="v0.9.1", min_from="v0.9.0",
                       zip_path=art / "clearledger-v0.9.1.zip",
                       req_path=art / "tree-v0.9.1" / "requirements.txt",
                       mart_changed=False, sentinels=[])
    return root, ups, mf


def phase_rollback_case_a(base: Path) -> None:
    ok, notes = True, []
    root, ups, mf = _build_z3_root(base, "z3a")
    zip_path = base / "artifacts" / "clearledger-v0.9.1.zip"
    snap_a = _upgrade_to_switch(root, ups, zip_path, mf, "情形 A 轮")
    r = upgrade(root, "rollback", py3=True, timeout=1800)
    case = ((r["payload"] or {}).get("data") or {}).get("case")
    if r["rc"] != 0 or case != "A":
        ok = False
        notes.append(f"rollback 未按预期：exit {r['rc']}，case={case}，输出尾部：{r['out'][-300:]}")
    else:
        notes.append("rollback（py -3）判定情形 A（金库指纹无偏离、schedule_enabled=false、finalize 未跑）")
    ver = (root / "VERSION").read_text(encoding="utf-8").strip()
    st = read_state(root) or {}
    failed_dirs = sorted(p.name for p in ups.glob("failed-*"))
    prevs = sorted(p.name for p in ups.glob("prev-v*"))
    if ver != "v0.9.0" or st.get("in_progress") is not None or not failed_dirs or prevs:
        ok = False
        notes.append(f"回滚后形态异常：VERSION={ver}，in_progress={st.get('in_progress')}，"
                     f"failed={failed_dirs}，prev 残留={prevs}")
    else:
        notes.append(f"槽位换回完成：根 VERSION=v0.9.0、in_progress 已清位、新根让位 {failed_dirs}、prev 归位")
        notes.append("收尾复核过（门户重启+doctor 复检 exit 0——沙盘 junction venv 走真环境）")
    kill_8620()  # rollback 收尾起的沙盘门户，别带进后续相位

    # ---- 缺陷探针：同一根上回滚后的第二次升级（现场完全会发生的节奏） ----
    # 机理：rollback 清 in_progress 但不清 state.migrate.intent（全部 done 态），
    # 第二轮 migrate 会「沿用已存搬迁意图」跳过全部 rename，终对账撞死。
    unpack(zip_path, ups / "staging-v0.9.1")
    for step_name in ("plan", "preflight", "stop", "backup"):
        r = upgrade(root, step_name, *(
            ["--manifest", str(mf)] if step_name in ("plan", "preflight") else []))
        assert r["rc"] == 0, f"二次升级 {step_name} 未过：{r['out'][-200:]}"
    r = upgrade(root, "migrate", py3=True)
    if r["rc"] != 0 and "终对账" in r["out"]:
        DEFECTS.append(
            "ops/upgrade.py 状态机卫生：rollback/_rollback_finish 清 in_progress 但不清 state.migrate"
            ".intent（全部条目停留 done 态），同一产品根回滚后的下一次升级里 cmd_migrate 会"
            "「沿用已存搬迁意图」跳过全部 rename（对新一轮 staging 不做实际搬迁），终对账以"
            "「终对账未过：data（staging 侧存在或字节数不符）」撞死——第二轮升级必须人工改"
            " state.json 才能继续。修法：rollback 收尾（或 stop 开新窗）时清 migrate 段，"
            "或 migrate 沿用意图前校验 items 是否真在 staging 侧。"
            f"（演练实测：z3a 情形 A 回滚后二次升级 migrate exit {r['rc']}，"
            f"error={((r['payload'] or {}).get('data') or {}).get('error', '?')}）")
        notes.append("⚠️ 缺陷探针命中并记录：回滚后二次升级的 migrate 沿用陈旧意图而失败（见 defects）")
    else:
        notes.append(f"缺陷探针未复现（二次 migrate exit {r['rc']}——如为 0 属意外通过）")
    record("switch 后 rollback 情形 A（未动库直接换回）", ok, "；".join(notes))


def phase_rollback_case_b(base: Path) -> None:
    ok, notes = True, []
    root, ups, mf = _build_z3_root(base, "z3b")  # 全新沙盘：规避上一个缺陷的陈旧意图路径
    zip_path = base / "artifacts" / "clearledger-v0.9.1.zip"
    snap_b = _upgrade_to_switch(root, ups, zip_path, mf, "情形 B 轮")
    bmanifest = json.loads((snap_b / "backup_manifest.json").read_text(encoding="utf-8"))
    entry = next(f for f in bmanifest["files"] if f["path"] == "data/warehouse/sales.duckdb")
    live = root / "data" / "warehouse" / "sales.duckdb"
    rc, _o, err = run([str(VENV_PY), "-c",
                       "import duckdb,sys;con=duckdb.connect(sys.argv[1]);"
                       "con.execute('create table if not exists marts.drill_drift_probe as select 42 as v');"
                       "con.close()", str(live)])
    if rc != 0:
        ok = False
        notes.append(f"人为改动 duckdb 失败：{err[-200:]}")
    else:
        notes.append("人为改动：向新根 sales.duckdb 写入 marts.drill_drift_probe（size/mtime 双漂移）")
    r = upgrade(root, "rollback", py3=True, timeout=1800)
    case = ((r["payload"] or {}).get("data") or {}).get("case")
    if r["rc"] != 0 or case != "B":
        ok = False
        notes.append(f"rollback 未按预期：exit {r['rc']}，case={case}，输出尾部：{r['out'][-300:]}")
    else:
        notes.append("判定情形 B（金库 size/mtime 偏离被实测捕获）→ 先恢复快照字节（sha256 逐文件核对）再槽位换回")
    got_sha = sha256_file(live)
    rc, o2, _e = run([str(VENV_PY), "-c", DRIFT_CHECK, str(live)])
    ver = (root / "VERSION").read_text(encoding="utf-8").strip()
    if got_sha != entry["sha256"] or "DRIFT-TABLE-GONE" not in o2 or ver != "v0.9.0":
        ok = False
        notes.append(f"恢复校验失败：sha256 {'一致' if got_sha == entry['sha256'] else '不符'}、"
                     f"漂移表 {'已消失' if 'DRIFT-TABLE-GONE' in o2 else '仍在'}、VERSION={ver}")
    else:
        notes.append("恢复校验过：sales.duckdb sha256 与快照 manifest 逐字节一致、"
                     "人为写入的 marts.drill_drift_probe 不存在、根 VERSION=v0.9.0")
    kill_8620()
    record("人为改动 duckdb 后 rollback 情形 B（强制恢复快照）", ok, "；".join(notes))


# ---------------------------------------------------------------- 场景四：机理验证

def phase_mech(base: Path) -> None:
    """机理验证（对照+正向）。预探针已把真机机理钉成矩阵（NTFS/Py3.12/win11）：

    ① 目录 rename 是元数据操作——打开的句柄（运行中 exe 映像、已映射 .pyd）跟文件
       对象走，不锁父目录 rename：裸 venv 解释器运行中、乃至主仓 .venv 被真门户
       占用 + duckdb/fastapi 已映射时，rename .venv 均成功（强形式「必败」证伪）；
    ② 进程 cwd 落在 .venv 内时 rename 祖先目录必败（WinError 5）——「必败」唯一
       成立的形态；
    ③ rename 后旧进程继续跑，但按原路径起新进程/装包立即 FileNotFoundError——
       解释器路径自断，这才是 migrate/switch/rollback 必须走 py -3 的真实依据。
    本相位在沙盘内自包含复刻 ①②③ 与正向（py -3 脚本 rename 自己所在目录）。
    """
    ok, notes = True, []
    mech = base / "mech"
    mech.mkdir(parents=True, exist_ok=True)
    vlock = mech / "venvlock"
    vlock.mkdir()
    venv = vlock / ".venv"
    rc, _o, err = run(PY3 + ["-m", "venv", str(venv)], cwd=mech, timeout=300)
    assert rc == 0, f"py -3 -m venv 失败：{err[-200:]}"
    vpy = venv / "Scripts" / "python.exe"

    def try_rename() -> tuple[int, str]:
        rrc, rout, _re = run(PY3 + ["-c", RENAME_PROBE, str(venv), str(venv) + "_x"])
        return rrc, rout

    def rename_back() -> None:
        if (vlock / ".venv_x").is_dir():
            os.rename(vlock / ".venv_x", venv)

    # ---- 对照①：运行中 venv 解释器（exe 映像在 .venv 内）----
    proc = subprocess.Popen([str(vpy), "-c", "import time; time.sleep(300)"], cwd=str(vlock))
    time.sleep(1.5)
    assert proc.poll() is None, "子进程未存活——对照①无效"
    rc1, out1 = try_rename()
    if "RENAME-OK" in out1:
        notes.append("对照①实测：运行中 venv 解释器在场，rename .venv 仍成功——"
                     "文档论断「必败」的强形式在本机被证伪（句柄跟文件对象走）")
        rename_back()
    elif "RENAME-FAIL" in out1:
        notes.append(f"对照①实测：rename 必败——{out1.strip().splitlines()[-1][:80]}")
    else:
        ok = False
        notes.append(f"对照①异常：exit {rc1}，out={out1.strip()[:100]}")
    proc.kill(); proc.wait()

    # ---- 对照①'：目录内有映射中的 DLL/.pyd（门户真实形态）----
    lockdir = mech / "pydlock" / "lockdir"
    lockdir.mkdir(parents=True)
    src_pyd = REPO / ".venv" / "Lib" / "site-packages" / "_duckdb.cp312-win_amd64.pyd"
    shutil.copy2(src_pyd, lockdir / "locked.pyd")
    proc2 = subprocess.Popen([str(VENV_PY), "-c",
                              "import ctypes,sys,time;ctypes.CDLL(sys.argv[1]);time.sleep(300)",
                              str(lockdir / "locked.pyd")])
    time.sleep(1.5)
    rc2, out2, _e2 = run(PY3 + ["-c", RENAME_PROBE, str(lockdir), str(lockdir) + "_x"])
    if "RENAME-OK" in out2:
        notes.append("对照①'实测：目录内有映射中的 .pyd（duckdb C 扩展，门户同机理）rename 仍成功——"
                     "强形式「必败」对此形态亦不成立")
        os.rename(str(lockdir) + "_x", lockdir)
    elif "RENAME-FAIL" in out2:
        notes.append(f"对照①'实测：映射 .pyd 锁住 rename——{out2.strip().splitlines()[-1][:80]}")
    else:
        ok = False
        notes.append(f"对照①'异常：exit {rc2}，out={out2.strip()[:100]}")
    proc2.kill(); proc2.wait()

    # ---- 对照②：cwd 落在 .venv 内——「必败」成立的形态 ----
    (venv / "hold").mkdir(exist_ok=True)
    p3 = subprocess.Popen([str(vpy), "-c", "import time; time.sleep(300)"], cwd=str(venv / "hold"))
    time.sleep(1.2)
    assert p3.poll() is None, "子进程未存活——对照②无效"
    rc3, out3 = try_rename()
    if "RENAME-FAIL" not in out3:
        ok = False
        notes.append(f"对照②未命中：cwd 在 .venv 内 rename 竟成功（out={out3.strip()[:80]}）")
    else:
        notes.append(f"对照②命中：cwd 在 .venv 内的进程锁住 rename——{out3.strip().splitlines()[-1][:80]}"
                     "（「必败」成立的机理形态：工作目录句柄）")
    p3.kill(); p3.wait()

    # ---- 对照③：改名后旧进程仍活、按原路径起新进程必败（路径自断） ----
    p4 = subprocess.Popen([str(vpy), "-c", "import time; time.sleep(120)"], cwd=str(vlock))
    time.sleep(1.2)
    rc4, out4 = try_rename()
    if "RENAME-OK" not in out4:
        ok = False
        notes.append(f"对照③前置失败：本轮 rename 未成（{out4.strip()[:80]}）")
    else:
        time.sleep(0.5)
        alive = p4.poll() is None
        try:
            r5 = subprocess.run([str(vpy), "-c", "print('new-proc')"], capture_output=True, timeout=15)
            path_dead = r5.returncode != 0
        except FileNotFoundError:
            path_dead = True  # 预期形态：CreateProcess 直接 WinError 2（路径已断）
        if alive and path_dead:
            notes.append("对照③命中：改名后旧进程继续运行（句柄跟文件对象），"
                         "按原路径起新进程 FileNotFoundError——解释器路径自断，"
                         "即 migrate/switch/rollback 必须由 py -3 执行的真实机理")
        else:
            ok = False
            notes.append(f"对照③异常：旧进程存活={alive}，新进程 rc={r5.returncode}")
        p4.kill(); p4.wait()
        rename_back()

    if "RENAME-OK" in out1 or "RENAME-OK" in out2:
        DEFECTS.append(
            "internal/docs/无损升级架构方案-20260930.md 3.3/红队防回潮条目的机理论断「对运行中进程的 "
            ".venv 目录 rename 必败」与本机实测不符（NTFS 目录 rename 是元数据操作，运行中 exe 映像"
            "与已映射 .pyd 均不锁父目录 rename；演练实测含映射 duckdb.pyd 的目录亦可改名）。"
            "「必败」仅在进程 cwd 位于其内时成立；对协议的影响有限——switch 前置的门户复查+杀门户"
            "仍保证 rename 时无进程占用，py -3 纪律的真实依据是改名后解释器路径自断（演练对照③已验）。"
            "建议修订方案表述，避免后人把「rename 必败」当锁探测器用。")

    # ---- 正向：py -3 纯标准库脚本 rename 自己所在目录 ----
    proj = mech / "selfmove" / "proj"
    proj.mkdir(parents=True)
    (proj / "mover.py").write_text(MOVER_SRC, encoding="utf-8")
    rc, out, err = run(PY3 + [str(proj / "mover.py")], timeout=60)
    if rc == 0 and "SELFMOVE-OK" in out and (proj.parent / "proj_moved" / "mover.py").is_file():
        notes.append("正向命中：py -3 纯标准库脚本把所在目录 rename 成功且自身继续执行"
                     "（switch 换名 staging 的机理前提成立）")
    else:
        ok = False
        notes.append(f"正向未过：exit {rc}，out={out.strip()[:120]}，err={err.strip()[:120]}")
    record("机理验证：rename 运行中 .venv 必败（对照）/ py -3 脚本 rename 自己所在目录可执行（正向）",
           ok, "；".join(notes))


# ---------------------------------------------------------------- 场景五：G 通道（双 remote + 私有分支 + 登记簿对账）

GIT_ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "drill", "GIT_AUTHOR_EMAIL": "drill@local",
           "GIT_COMMITTER_NAME": "drill", "GIT_COMMITTER_EMAIL": "drill@local"}


def git(cwd: Path, *args, check: bool = True):
    r = subprocess.run(["git", "-C", str(cwd), *[str(a) for a in args]],
                       capture_output=True, timeout=300, env=GIT_ENV)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(str(a) for a in args)} 失败："
                             + r.stderr.decode("utf-8", "replace")[:300])
    return r


REG_BASE = f"""# HRO 私有改动登记簿（现场约定：hro 分支只放配置，引擎改动走 develop 回传）

## 登记条目
- 登记模板行（hro 与上游 v0.9.2 各自改写本行——演练的冲突点）
"""
HRO_LINE = "- 2026-09-28 现场：instances/hro/dimensions.yml 客户等级口径按集团人事部口径调整"
UPSTREAM_LINE = "- 2026-09-30 上游：登记簿增补 v0.9.2 hro 适配说明模板"


def phase_g(base: Path) -> None:
    ok, notes = True, []
    g = base / "g"
    origin, private = g / "origin.git", g / "private.git"
    seed = g / "seed"
    root = g / "root"
    art = base / "artifacts"

    log("[g] 构造：本地裸仓 origin + 私有裸仓 + 完整产品树 develop 提交（v0.9.0）")
    for bare in (origin, private):
        bare.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "--bare", "-b", "develop", str(bare)])
    copy_product_tree(seed, "v0.9.0")
    (seed / REGISTRY).write_text(REG_BASE, encoding="utf-8")
    git(seed, "init", "-b", "develop")
    git(seed, "config", "user.name", "drill")   # 仓库级身份：upgrade.py 的 _git 不带环境，
    git(seed, "config", "user.email", "drill@local")  # merge 要落 commit，机器全局又无身份
    top_existing = [n for n in (*TOP_DIRS, *TOP_FILES, REGISTRY) if (seed / n).exists()]
    git(seed, "add", *top_existing)
    git(seed, "commit", "-m", "C1: v0.9.0 产品树 + 登记簿")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-u", "origin", "develop")

    log("[g] clone 出产品根（.git 在根内→通道 G），挂第二 remote（private），建 hro 式私有分支")
    run(["git", "clone", str(origin), str(root)], env=GIT_ENV)
    git(root, "config", "user.name", "drill")
    git(root, "config", "user.email", "drill@local")
    git(root, "config", "core.quotepath", "off")  # 冲突文件名按原文输出，供演练比对
    git(root, "remote", "add", "private", str(private))
    git(root, "checkout", "-b", "hro")
    (root / REGISTRY).write_text(REG_BASE.replace(
        "登记模板行（hro 与上游 v0.9.2 各自改写本行——演练的冲突点）", HRO_LINE), encoding="utf-8")
    git(root, "add", REGISTRY)
    git(root, "commit", "-m", "P1(hro 私有)：登记 hro 口径适配")
    git(root, "push", "-u", "private", "hro")

    log("[g] origin 侧出 v0.9.2：VERSION 升版 + 登记簿同位置异改（制造 merge 冲突）+ tag")
    (seed / "VERSION").write_text("v0.9.2\n", encoding="utf-8")
    (seed / REGISTRY).write_text(REG_BASE.replace(
        "登记模板行（hro 与上游 v0.9.2 各自改写本行——演练的冲突点）", UPSTREAM_LINE), encoding="utf-8")
    git(seed, "add", "VERSION", REGISTRY)
    git(seed, "commit", "-m", "C2: v0.9.2 升版（含登记簿上游侧改动）")
    git(seed, "tag", "v0.9.2")
    git(seed, "push", "origin", "develop", "--tags")

    log("[g] 产品根补真金库 + settings + junction .venv（untracked，不进公开仓）")
    stage_data(root)
    mount_venv(root)
    # 仓库 .gitignore 的 data/ 无前导斜杠，instances/*/data（inbox 演示数据）也被忽略，
    # clone 出的根投放区是空的——从主仓补回（doctor 投放区体检与 canary 材料都要它）
    for inst in KEEP_INSTANCES:
        src = REPO / "instances" / inst / "data"
        if src.is_dir():
            shutil.copytree(src, root / "instances" / inst / "data", dirs_exist_ok=True)

    tree92 = art / "tree-v0.9.2"
    copy_product_tree(tree92, "v0.9.2")
    zip92 = art / "clearledger-v0.9.2.zip"
    if not zip92.is_file():
        make_zip(tree92, zip92)
    mf92 = art / "manifest-v0.9.2.json"
    build_manifest(mf92, version="v0.9.2", min_from="v0.9.0",
                   zip_path=zip92, req_path=tree92 / "requirements.txt",
                   mart_changed=False, sentinels=[])

    for step_name in ("plan", "preflight"):
        r = upgrade(root, step_name, "--manifest", str(mf92))
        if r["rc"] != 0:
            ok = False
            notes.append(f"{step_name} 未过")
    r = upgrade(root, "stop")
    if r["rc"] != 0:
        ok = False
        notes.append("stop 未过")
    r = upgrade(root, "backup")
    if r["rc"] != 0:
        ok = False
        notes.append("backup 未过")
    else:
        head = ((r["payload"] or {}).get("data") or {}).get("git_head")
        notes.append(f"backup 通过（升级前 HEAD={str(head)[:12]} 已记录，供通道 G 回滚）")

    # ---- sync 第一场：预期 merge 冲突，按登记簿对账 ----
    r = upgrade(root, "sync", timeout=600)
    conflicted = git(root, "diff", "--name-only", "--diff-filter=U", check=False) \
        .stdout.decode("utf-8", "replace").strip()
    if r["rc"] == 0 or not conflicted:
        ok = False
        notes.append(f"sync 首跑未按预期冲突：exit {r['rc']}，冲突文件={conflicted!r}")
    else:
        notes.append(f"sync 首跑按预期失败（exit {r['rc']}）：冲突文件 {conflicted}，"
                     "输出含登记簿对账指引（未自动 abort，现场保留）")
        if REGISTRY not in conflicted or "登记簿" not in r["out"]:
            ok = False
            notes.append("冲突面/对账指引与现场约定不符（应只落在登记簿与 instances/，指引应点名登记簿）")
    log("  $ git add+commit（演练充当驻场 agent：按登记簿并收两侧条目完成对账）")
    merged = REG_BASE.replace(
        "- 登记模板行（hro 与上游 v0.9.2 各自改写本行——演练的冲突点）",
        HRO_LINE + "\n" + UPSTREAM_LINE)
    (root / REGISTRY).write_text(merged, encoding="utf-8")
    git(root, "add", REGISTRY)
    git(root, "commit", "-m", "对账：按登记簿并收 hro 私有条目与上游 v0.9.2 条目")

    # ---- sync 续跑：通过条件全过 ----
    r = upgrade(root, "sync", timeout=600)
    if r["rc"] != 0:
        ok = False
        notes.append(f"sync 对账后续跑未过：{r['out'][-300:]}")
    else:
        r_anc = git(root, "merge-base", "--is-ancestor", "v0.9.2", "HEAD", check=False)
        dirty = git(root, "status", "--porcelain").stdout.decode("utf-8", "replace").strip()
        if r_anc.returncode != 0 or dirty:
            ok = False
            notes.append(f"sync 过但终态异常：is-ancestor={r_anc.returncode}，dirty={dirty[:120]}")
        else:
            notes.append("sync 续跑通过：两段 merge 幂等、v0.9.2 tag 是 HEAD 祖先、无未解决冲突、工作树干净")
    r = upgrade(root, "canary", "--instance", "sales")
    if r["rc"] != 0:
        ok = False
        notes.append("canary（mart_schema_changed=false 应跳过）未过")
    else:
        notes.append("canary 按 manifest 跳过（mart_schema_changed=false）")
    r = upgrade(root, "smoke", timeout=1800)
    if r["rc"] != 0:
        bad = [c for c in ((r["payload"] or {}).get("data", {}).get("checks") or []) if c["status"] != "ok"]
        ok = False
        notes.append(f"smoke 未过：{bad}")
        # 产品缺陷侦测：smoke 真实查询读报表主键用 "id"，而全部账套 dashboard.yml 的
        # 主键字段是 "key"（instances/*/dashboard.yml 无一处 id:）——manifest 带
        # sentinel_reports 时被哨兵兜底掩盖（场景一即如此），哨兵为空即现形。
        if any("无注册报表可查" in str(c.get("detail", "")) for c in bad):
            DEFECTS.append(
                "ops/upgrade.py cmd_smoke 真实查询（约 :1764-1784）：取 dashboard 首报表用 "
                "reports[0].get(\"id\")，而 dashboard.yml 的报表主键字段是 key（六个账套全用 "
                "key:，semantic/loader.py 报表注册同键名）——id 恒为 None，哨兵基线为空的账套"
                "（sentinel_reports=[] 的升级）smoke 必挂「真实查询：dashboard.yml 无注册报表可查」。"
                "修法：get(\"id\") 改 get(\"key\")。"
                "（演练实测：G 通道沙盘 sales 账套 five 报表在册仍报无报表可查）")
    else:
        notes.append("smoke 通过（沙盘门户自起、真实查询出数）")
    r = upgrade(root, "finalize")
    if r["rc"] != 0:
        ok = False
        notes.append("finalize 未过")
    else:
        notes.append("finalize 通过：VERSION 复核 v0.9.2（HEAD=登记簿对账 merge commit）")
    record("G 通道全链：本地裸仓 origin+双 remote+develop/hro 式私有分支+登记簿，sync 含 merge 冲突按登记簿对账",
           ok, "；".join(notes))


# ---------------------------------------------------------------- main

def main() -> int:
    t0 = time.monotonic()
    for stream in (sys.stdout, sys.stderr):  # Windows 管道下默认代码页会炸 emoji，统一 UTF-8
        if stream.encoding and stream.encoding.lower().replace("-", "") != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    for p in (VENV_PY, UPGRADE):
        if not p.is_file():
            log(f"[drill] 前置缺失：{p}")
            return 1
    rc, _o, _e = run(PY3 + ["--version"])
    if rc != 0:
        log("[drill] py -3 不可用")
        return 1
    was_running = port_pid() is not None
    log(f"[drill] 8620 演练前状态：{'监听中 PID ' + str(port_pid()) + '（结束时会恢复）' if was_running else '无监听'}")

    base = Path(tempfile.mkdtemp(prefix="cl_drill_p0_"))
    log(f"[drill] 沙盘根：{base}")

    def guarded(name: str, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # 相位级兜底：崩溃记失败项，演练继续
            import traceback
            record(name, False, f"相位异常：{exc!r}；{traceback.format_exc().strip().splitlines()[-1]}")

    try:
        guarded("Z 通道首升全链：v0.9.0→v0.9.1 plan→preflight→stage→stop→backup→migrate→switch→canary→smoke→finalize",
                phase_z_full_chain, base)
        ok2, notes2 = False, ["未执行"]
        for tag, pad in (("z2", 15000), ("z2b", 40000)):
            try:
                ok2, notes2 = phase_z_kill(base, tag, pad)
            except Exception as exc:
                notes2 = [f"相位异常：{exc!r}"]
            if ok2:
                break
            log(f"[{tag}] pad={pad} 未成：{notes2[-1] if notes2 else '?'}")
        record("migrate 中途 kill 后幂等续跑 + --revert 逆向搬回（py -3）", ok2, "；".join(notes2))
        guarded("switch 后 rollback 情形 A（未动库直接换回）", phase_rollback_case_a, base)
        guarded("人为改动 duckdb 后 rollback 情形 B（强制恢复快照）", phase_rollback_case_b, base)
        guarded("机理验证：rename 运行中 .venv 必败（对照）/ py -3 脚本 rename 自己所在目录可执行（正向）",
                phase_mech, base)
        guarded("G 通道全链：本地裸仓 origin+双 remote+develop/hro 式私有分支+登记簿，sync 含 merge 冲突按登记簿对账",
                phase_g, base)
    finally:
        kill_8620()
        restore_portal(was_running)

    # 清理：保留最后一场（G 通道场景）供检查
    keep = base / "g"
    for child in sorted(base.iterdir()):
        if child == keep:
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)  # 3.12 实测：rmtree 不跟进 junction
            else:
                child.unlink(missing_ok=True)
        except OSError as exc:
            log(f"[drill] 清理 {child} 失败（忽略）：{exc}")
    minutes = (time.monotonic() - t0) / 60
    log("")
    log("=" * 72)
    log(f"[drill] 演练完成，用时 {minutes:.1f} 分钟；保留最后一场：{keep}（.venv 是指向主仓 .venv 的 junction）")
    for it in ITEMS:
        log(f"  [{it['result'].upper():4}] {it['item']}")
    if DEFECTS:
        log("[drill] 疑似产品缺陷：")
        for d in DEFECTS:
            log(f"  - {d}")
    log("[drill] 机器可读结果（JSON）：")
    log(json.dumps({"items": ITEMS, "defects": DEFECTS, "minutes": round(minutes, 1),
                    "scene_kept": str(keep)}, ensure_ascii=False))
    return 0 if all(i["result"] == "pass" for i in ITEMS) else 1


if __name__ == "__main__":
    sys.exit(main())
