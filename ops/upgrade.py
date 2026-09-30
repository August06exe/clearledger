# -*- coding: utf-8 -*-
"""明账 ClearLedger — 无损升级协议引擎（骨架版）

规格：internal/docs/无损升级架构方案-20260930.md（3.1 通道与布局、3.3 协议步骤、
6.2 upgrade-manifest.json、6.4 agent 认领 SOP）。本文件是该方案的落点 1。

编码约束（3.3 解释器表，红队三轮防回潮条目，违反即事故）：
- 本文件顶层 import 只允许标准库——migrate/switch/rollback 由 py -3（系统
  Python 3.8+）执行，脚本必须不依赖 .venv 任何包；
- migrate/switch/rollback 三个子命令的代码路径只允许 os/json/stat/hashlib/
  shutil 级别的标准库操作；
- 非标准库依赖（未来的 duckdb 只读体检等）只允许在对应子命令函数体内
  lazy import，且绝不允许出现在 migrate/switch/rollback 路径上。

解释器表（3.3，命令行逐条见 6.4）：
  plan / preflight / stage / stop / backup   → 旧根 .venv\\Scripts\\python.exe
  migrate / switch / rollback                → py -3
  refresh / canary / smoke / finalize / prune→ 产品根 .venv\\Scripts\\python.exe
首升场景（现场尚无本脚本）：用已解包 staging 内的本文件，一律加 --root <旧根>。

子命令实现状态：
  已实现   plan / preflight / status / stop / backup（含哨兵基线采集）/ migrate /
           switch / sync / canary / smoke / rollback / finalize / prune
  占位     stage（下载/解包属网络重活，后续批次；首升按 6.4 引导两命令手工解包）
已知边界：①refresh 未设独立子命令（骨架命名面未列），其依赖核对并入 smoke，
  强制 pip install -r 仍由 launcher/手册承担；②finalize 不代跑正式三步链与人类
  验收（按 AGENTS 配方/R-14）；③窗口生命周期：stop 开窗（in_progress 置位），
  rollback 与 prune 关窗（清位）；finalize 后窗口仍开、且回滚必走情形 B（Gitea 铁律）。

通道与布局判定（3.1）：
  通道 G = 产品根有 .git（git 双仓制）；通道 Z = 无 .git（zip 槽位换名）；
  模式 A = instances/ 与 data/ 都在产品根内；模式 B = 都不在（平级分离）；
  只有一个在 → 探测不明，fail，禁止猜。

退出码约定：
  0  通过（含 warn / skipped / deferred）
  1  失败——JSON 列出未过项与原因；停机窗步骤失败即中止窗口
  2  plan 专用：本地版本低于 min_upgradable_from（报告含中间版本清单）；
     注意 argparse 的用法错误同样是 2，区别在用法错误伴随 usage 文本
  3  本骨架专用：子命令占位未实现

输出约定：每步先打人类可读中文行；--json 时末行追加完整机器 JSON。
每次运行的最终 JSON 一律留档 data/upgrade/logs/<时间戳>_<子命令>.json（6.4）。
状态机 data/upgrade/state.json：plan/preflight 更新 channel/mode/history 并由
plan 落 last_plan（目标版本+manifest，停机窗四步的数据源）；stop 置 in_progress
（升级窗口开）；backup/migrate/switch 各自追加阶段记录；rollback/finalize 负责
清位（后续批次）。preflight 的「无未完成升级」检查读 in_progress。
状态文件随 data/ 整体搬迁（3.3）——migrate 后它在 staging/data/ 下，switch 后
回到产品根 data/ 下；状态定位一律经 _state_file_for 双址探测，绝不因写状态在
旧根凭空重造 data/（防布局探测被污染，见 data_dir 的防污染纪律）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 共用判定抽至 upgrade_common（doctor/launcher/upgrade 三入口一处实现，方案落点 7f）。
# py -3 执行本文件时脚本目录（ops/）在 sys.path[0]，同级模块可直接 import；
# upgrade_common 同样纯标准库（见其文件头约束）。
from upgrade_common import (RELEASES_API, UpgradeError, _http_get, data_dir,
                            dependency_check as _dependency_check,
                            detect_channel_layout, fetch_latest_release,
                            fetch_release_tags, parse_semver, read_local_version,
                            semver_cmp, window_mode)

ROOT = Path(__file__).resolve().parents[1]

STEPS = ("plan", "preflight", "stage", "stop", "backup", "migrate", "switch",
         "sync", "canary", "smoke", "rollback", "finalize", "prune", "status")
STEP_NOT_IMPLEMENTED_NOTE = {
    "stage": "骨架占位——下载/解包/sha256/builtin diff 内部逻辑后续批次实现"
             "（首升自举时先按 6.4 的引导两命令手工解包出 staging，stage 会退化为校验）",
}

MANIFEST_ASSET = "upgrade-manifest.json"  # 每个 Release 绑定的机器可读资产（6.2）
# 6.2 字段清单：名字 → 校验器（None 表示仅要求存在）
MANIFEST_FIELDS: dict[str, object] = {
    "version": "semver",
    "min_upgradable_from": "semver",
    "zip_sha256": "sha256",
    "requirements_sha256": "sha256",
    "duckdb_version": "str",
    "tenants_builtin": "list_str",
    "launcher_rebuilt": "bool",
    "mart_schema_changed": "bool",
    "config_schema_version": "dict",
    "contract_version": "int",
    "contract_changes": "list",
    "sentinel_reports": "list_str",
    "auto_apply": "bool",
    "requires_manual_steps": "list",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INSTANCE_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")  # 沿工作台实例名纪律
_SIX_YML = ("instance.yml", "sources.yml", "wide.yml", "dimensions.yml",
            "metrics.yml", "dashboard.yml")  # 与 ops/backup.py 同源，下一轮做共享收敛
_STATE_HISTORY_CAP = 20


def _fail(msg: str, lines: list[str]) -> UpgradeError:
    return UpgradeError(msg, lines)


# ---------------------------------------------------------------- 基础件

def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding and stream.encoding.lower().replace("-", "") != "utf8":
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def validate_semver(value: str) -> str:
    """argparse type 校验器：格式错按用法错误退出（exit 2 + usage 文本）。"""
    try:
        parse_semver(value)
    except UpgradeError as exc:
        raise argparse.ArgumentTypeError(str(exc))
    return value


def validate_instance(value: str) -> str:
    if not _INSTANCE_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"账套名 {value!r} 非法（沿实例名纪律：字母数字开头，禁 . / \\）")
    return value


# ---------------------------------------------------------------- 探测（3.1）

# ---------------------------------------------------------------- manifest（6.2）

def load_manifest(target: str | None, manifest_spec: str | None) -> tuple[dict, str]:
    """manifest 两取法：--manifest 收本地路径或 http(s) URL；--target 拼 Release 资产
    URL；两者都缺时自动查 Releases latest。返回（manifest 对象, 来源描述）。"""
    if manifest_spec:
        if re.match(r"^https?://", manifest_spec):
            try:
                raw = _http_get(manifest_spec)
            except Exception as exc:
                raise UpgradeError(f"manifest URL 拉取失败：{manifest_spec}：{exc}")
            return json.loads(raw.decode("utf-8")), f"url:{manifest_spec}"
        p = Path(manifest_spec)
        if not p.is_file():
            raise UpgradeError(f"manifest 本地文件不存在：{manifest_spec}")
        return json.loads(p.read_text(encoding="utf-8")), f"file:{p}"
    if target:
        url = f"https://github.com/August06exe/clearledger/releases/download/{target}/{MANIFEST_ASSET}"
        try:
            raw = _http_get(url)
        except Exception as exc:
            raise UpgradeError(f"manifest 拉取失败：{url}：{exc}")
        return json.loads(raw.decode("utf-8")), f"url:{url}"
    rel = fetch_latest_release()
    tag = rel.get("tag_name", "")
    asset = next((a for a in rel.get("assets", [])
                  if a.get("name") == MANIFEST_ASSET), None)
    if asset is None:
        raise UpgradeError(f"Release {tag!r} 未绑定 {MANIFEST_ASSET} 资产（6.1 要求四件资产同版本）")
    url = asset["browser_download_url"]
    try:
        raw = _http_get(url)
    except Exception as exc:
        raise UpgradeError(f"manifest 拉取失败：{url}：{exc}")
    return json.loads(raw.decode("utf-8")), f"url:{url}"


def validate_manifest(m: dict) -> list[str]:
    """按 6.2 十四字段做存在性+类型校验；zip_sha256 存在是 plan 通过条件（3.3 步骤一）。"""
    issues: list[str] = []
    if not isinstance(m, dict):
        return ["manifest 顶层不是 JSON 对象"]
    for name, kind in MANIFEST_FIELDS.items():
        if name not in m:
            issues.append(f"缺字段 {name}")
            continue
        v = m[name]
        bad = False
        if kind == "semver":
            try:
                parse_semver(v)
            except UpgradeError:
                bad = True
        elif kind == "sha256":
            bad = not (isinstance(v, str) and _SHA256_RE.match(v))
        elif kind == "str":
            bad = not isinstance(v, str)
        elif kind == "bool":
            bad = not isinstance(v, bool)
        elif kind == "int":
            bad = not isinstance(v, int) or isinstance(v, bool)
        elif kind == "dict":
            bad = not isinstance(v, dict)
        elif kind == "list":
            bad = not isinstance(v, list)
        elif kind == "list_str":
            bad = not (isinstance(v, list) and all(isinstance(x, str) for x in v))
        if bad:
            issues.append(f"字段 {name} 类型不符（期望 {kind}）")
    return issues


def parse_upgrade_md(root: Path) -> dict[str, str]:
    """仓库根 UPGRADE.md 按版本分节（## vX.Y.Z），返回 版本→节文本。
    4 节落点 4 尚未交付时文件缺失，返回空并如实上报。"""
    path = root / "UPGRADE.md"
    if not path.is_file():
        return {}
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(v\d+\.\d+\.\d+)\b", line)
        if m:
            if current:
                sections[current] = "\n".join(buf).strip()
            current, buf = m.group(1), []
        elif current:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections


# ---------------------------------------------------------------- 体积构成（preflight 磁盘检查）

def _dir_size(path: Path) -> int:
    total = 0
    for d, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            try:
                total += (Path(d) / fn).stat().st_size
            except OSError:
                pass
    return total


def snapshot_objects_size(root: Path) -> dict:
    """快照对象实测：镜像 ops/backup.py 的备份范围（data/backup 不嵌套备份）。
    路径经 data_dir 定位（模式 B 的 data/ 在产品根平级）。"""
    parts: dict[str, int] = {}
    dd = data_dir(root)
    wh = dd / "warehouse"
    if wh.is_dir():
        size = 0
        for db in wh.glob("*.duckdb"):
            size += db.stat().st_size
            wal = db.with_name(db.name + ".wal")
            if wal.exists():
                size += wal.stat().st_size
        parts["warehouse(+.wal)"] = size
    for name, rel in (("runs", dd / "runs"), ("logs", root / "logs")):
        if rel.is_dir():
            parts[name] = _dir_size(rel)
    inst_size = 0
    inst_root = root / "instances"
    if inst_root.is_dir():
        for inst in inst_root.iterdir():
            if not inst.is_dir() or not (inst / "instance.yml").exists():
                continue
            for f in _SIX_YML:
                if (inst / f).is_file():
                    inst_size += (inst / f).stat().st_size
            ch = inst / "onboarding" / "config_history"
            if ch.is_dir():
                inst_size += _dir_size(ch)
            elif ch.is_file():
                inst_size += ch.stat().st_size
            idata = inst / "data"  # inbox 原始源文件（B2：与 ops/backup.py 范围同口径）
            if idata.is_dir():
                inst_size += _dir_size(idata)
    for name in ("openapi_keys.json", "settings.json"):
        p = dd / name
        if p.is_file():
            inst_size += p.stat().st_size
    for name in ("VERSION", "requirements.txt"):
        p = root / name
        if p.is_file():
            inst_size += p.stat().st_size
    parts["instances配置+单文件"] = inst_size
    return parts


def code_size_estimate(root: Path) -> int:
    """旧代码体积估计（prev 份额 / 新版解包体积的近似）：排除 .venv、data、logs、
    instances、.git——这些随 migrate 整体 rename 不占双份（3.1 磁盘预算）。"""
    excluded = {".venv", "data", "logs", "instances", ".git", "__pycache__"}
    total = 0
    for d, dirnames, filenames in os.walk(root):
        dirnames[:] = [n for n in dirnames if n not in excluded]
        for fn in filenames:
            try:
                total += (Path(d) / fn).stat().st_size
            except OSError:
                pass
    return total


# ---------------------------------------------------------------- 环境检查件

def probe_port_8620() -> dict:
    """无监听为佳；有监听记录 PID（真杀留给停机步骤，3.3 步骤二）。"""
    s = socket.socket()
    s.settimeout(1.5)
    listening = False
    try:
        s.connect(("127.0.0.1", 8620))
        listening = True
    except Exception:
        pass
    finally:
        s.close()
    if not listening:
        return {"listening": False, "pid": None}
    pid = None
    if os.name == "nt":
        try:
            raw = subprocess.run(["netstat", "-ano"], capture_output=True,
                                 timeout=15).stdout
            out = raw.decode("utf-8", errors="ignore")  # 只找 ASCII 片段，容忍任意代码页
            for line in out.splitlines():
                if ":8620" in line and "LISTENING" in line.upper():
                    pid = line.split()[-1]
                    break
        except Exception:
            pid = "unknown（netstat 解析失败）"
    return {"listening": True, "pid": pid}


def schedule_d11_state(root: Path) -> dict:
    """D11：schedule_enabled=true 时 smoke 起门户即触发补跑写真实库，
    回滚情形判定一律按情形 B（3.3 步骤九/十）。preflight 只记录不定罪。"""
    p = data_dir(root) / "settings.json"
    if not p.is_file():
        return {"schedule_enabled": False, "note": "settings.json 不存在（默认完全手动）"}
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"schedule_enabled": None, "note": f"settings.json 损坏（{exc}）——按 enabled 保守处理"}
    enabled = bool(cfg.get("schedule_enabled", False))
    return {"schedule_enabled": enabled,
            "note": "开启：升级窗口内起门户会补跑写库（D11），回滚判定视同情形 B" if enabled
                    else "关闭：无补跑写库风险"}


def backup_target_writable(root: Path, layout: dict) -> tuple[bool, str]:
    d = data_dir(root, layout) / "backup"
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / f".upgrade_preflight_probe_{os.getpid()}.tmp"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return True, str(d)
    except Exception as exc:
        return False, f"{d} 不可写：{exc}"


# ---------------------------------------------------------------- 状态机

def state_path(root: Path) -> Path:
    return data_dir(root) / "upgrade" / "state.json"


def read_state(root: Path) -> dict | None:
    p = state_path(root)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"format": "clearledger-upgrade-state/?", "corrupt": str(exc),
                "note": "state.json 解析失败——按有未完成升级保守处理，人工核查后删除或修复"}


def write_state(root: Path, state: dict) -> None:
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def update_state_history(root: Path, step: str, exit_code: int, status: str,
                         summary: str, env: dict) -> None:
    """plan/preflight 落状态（3.4：这两步只写 data/upgrade/，agent 自主执行）。
    status 只读不写；占位子命令只留运行日志、不动状态机。"""
    state = read_state(root) or {}
    if state.get("format") != "clearledger-upgrade-state/1":
        state = {"format": "clearledger-upgrade-state/1"}
    state.update({"root": str(root), "updated_at": now_iso(), **env})
    history = state.get("history", [])
    history.append({"step": step, "at": now_iso(), "exit_code": exit_code,
                    "status": status, "summary": summary})
    state["history"] = history[-_STATE_HISTORY_CAP:]
    write_state(root, state)


def archive_log(root: Path, step: str, payload: dict, argv: list[str]) -> str:
    """运行日志留档（6.4：每步 JSON 落 data/upgrade/logs/）。落点随 data/ 走：
    根内 data → 各 staging 的 data → 平级 data；都没有（异常态）拒档并告警，
    绝不在旧根凭空造 data/ 污染布局探测。"""
    candidates = [root / "data" / "upgrade" / "logs"]
    ups = root.parent / "upgrade"
    if ups.is_dir():
        candidates += [s / "data" / "upgrade" / "logs" for s in sorted(ups.glob("staging-v*"))]
    candidates.append(root.parent / "data" / "upgrade" / "logs")  # 模式 B 平级
    home = next((c for c in candidates if (c.parent.parent).is_dir()), None)  # c/../.. = data/
    if home is None:
        print(f"[{step}] 警告：data/ 不在预期位置（根内/平级/staging 均无），"
              f"运行日志不留档——人工检查布局", file=sys.stderr)
        return ""
    home.mkdir(parents=True, exist_ok=True)
    name = f"{now_stamp()}_{step}.json"
    (home / name).write_text(
        json.dumps({**payload, "argv": argv}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return name


# ---------------------------------------------------------------- 子命令：plan（3.3 步骤一）

def cmd_plan(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """plan：只读。拉 manifest、比对本地 VERSION、拼分诊报告；报告写盘 exit 0；
    本地低于 min_upgradable_from 输出中间版本清单 exit 2；失败不改任何文件。"""
    root: Path = ctx.root
    lines: list[str] = []
    layout = detect_channel_layout(root)
    if not layout["ok"]:
        raise UpgradeError("；".join(layout["detail"]))
    try:
        local_raw = read_local_version(root)
        local = parse_semver(local_raw)
    except Exception as exc:
        raise UpgradeError(f"本地 VERSION 不可读或不合法：{exc}（preflight 通过条件之一）")
    try:
        manifest, source = load_manifest(ctx.target, ctx.manifest)
    except UpgradeError:
        raise
    except Exception as exc:
        raise UpgradeError(f"manifest 解析失败（{exc}）——内容不是合法 JSON")
    issues = validate_manifest(manifest)
    if issues:
        raise UpgradeError("manifest 未过 6.2 字段校验：" + "；".join(issues))
    target_ver = manifest["version"]
    target = parse_semver(target_ver)
    min_from = parse_semver(manifest["min_upgradable_from"])

    direction = semver_cmp(target, local)
    below_min = semver_cmp(local, min_from) < 0
    version_check = {
        "local": local_raw, "target": target_ver,
        "min_upgradable_from": manifest["min_upgradable_from"],
        "direction": {1: "升级", 0: "同版本", -1: "目标低于本地（不支持降级）"}[direction],
        "below_min_upgradable_from": below_min,
    }
    lines.append(f"[plan] 本地 {local_raw} → 目标 {target_ver}"
                 f"（min_upgradable_from={manifest['min_upgradable_from']}，{source}）")
    if direction <= 0:
        raise UpgradeError(f"版本方向检查未过：{version_check['direction']}——"
                           f"目标必须高于本地（6.1：tag 是唯一升级单位）")

    # 分诊材料一：UPGRADE.md 本地版→目标版的节（落点 4 未交付时如实标注）
    sections = parse_upgrade_md(root)
    picked: dict[str, str] = {}
    for ver, text in sections.items():
        v = parse_semver(ver)
        if semver_cmp(v, local) > 0 and semver_cmp(v, target) <= 0:
            picked[ver] = text
    upgrade_md = {"exists": bool(sections), "sections_used": sorted(picked),
                  "note": "" if sections else
                  "UPGRADE.md 不存在（落点 4 首版未建）——分诊暂只有 manifest 项；"
                  "发布前必须补齐（6.3）"}

    # 分诊材料二：中间版本清单（本地 < min_upgradable_from 时）
    intermediate: list[str] = []
    intermediate_note = ""
    if below_min:
        tags = fetch_release_tags()
        for tag in tags:
            try:
                v = parse_semver(tag)
            except UpgradeError:
                continue
            if semver_cmp(v, local) > 0 and semver_cmp(v, target) < 0:
                intermediate.append(tag)
        intermediate = sorted(set(intermediate), key=parse_semver)
        if not intermediate:
            intermediate_note = ("无法枚举中间版本（Release API 不可达或无记录）——"
                                 "按手册 R-14 人工确认逐版升级路径")

    triage = {
        "incompatible": [s for s in manifest.get("requires_manual_steps", [])
                         if "不兼容" in s or "incompatible" in s.lower()],
        "requires_manual_steps": manifest.get("requires_manual_steps", []),
        "metric_changes": picked,  # 口径变更表在 UPGRADE.md 各节内（6.3）
        "contract_changes": manifest.get("contract_changes", []),
        "contract_version": manifest.get("contract_version"),
        "sentinel_reports": manifest.get("sentinel_reports", []),
        "canary_required": bool(manifest.get("mart_schema_changed")),
        "auto_apply": bool(manifest.get("auto_apply")),
        "duckdb_version": manifest.get("duckdb_version"),
        "config_schema_version": manifest.get("config_schema_version", {}),
        "human_approval_required": True,  # 3.4：停机及之后默认须人类点头
    }
    lines.append(f"[plan] 分诊：canary={'需要' if triage['canary_required'] else '跳过'}"
                 f"｜人工确认项 {len(triage['requires_manual_steps'])} 条"
                 f"｜契约变更 {len(triage['contract_changes'])} 条"
                 f"｜哨兵报表 {triage['sentinel_reports']}")
    if picked:
        lines.append(f"[plan] UPGRADE.md 纳入节：{', '.join(sorted(picked))}")

    report = {
        "format": "clearledger-upgrade-plan-report/1",
        "generated_at": now_iso(), "root": str(root),
        "channel": layout["channel"], "mode": layout["mode"],
        "manifest_source": source, "manifest": manifest,
        "version_check": version_check, "upgrade_md": upgrade_md,
        "intermediate_versions": intermediate,
        "intermediate_note": intermediate_note,
        "triage": triage,
    }
    if below_min:
        report["blocked"] = ("本地版本低于 min_upgradable_from——需先升到中间版本；"
                             "本报告含中间版本清单（exit 2 语义）")
    out_dir = data_dir(root) / "upgrade"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"plan_{target_ver}_{now_stamp()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # last_plan 落状态机：stop/backup/migrate/switch 的命令面无参（6.4），目标版本、
    # tenants_builtin 等只能经状态机传递（3.3：状态机 data/upgrade/state.json）
    state = read_state(root) or {"format": "clearledger-upgrade-state/1"}
    state["format"] = "clearledger-upgrade-state/1"
    state["last_plan"] = {"target": target_ver, "at": now_iso(), "source": source,
                          "manifest": manifest}
    write_state(root, state)

    status = "blocked" if below_min else "ok"
    exit_code = 2 if below_min else 0
    try:
        shown = out.relative_to(root).as_posix()
    except ValueError:  # 模式 B：data/ 在产品根平级，不在 root 之下
        shown = str(out)
    lines.append(f"[plan] 分诊报告：{shown}（exit {exit_code}）")
    if below_min:
        shown = intermediate or "无法枚举"
        lines.append(f"[plan] 本地 {local_raw} 低于 {manifest['min_upgradable_from']}——"
                     f"中间版本：{shown}")
    return exit_code, status, lines, {"report": shown,
                                      "report_path": str(out),
                                      "version_check": version_check,
                                      "triage": triage,
                                      "intermediate_versions": intermediate}


# ---------------------------------------------------------------- 子命令：preflight（3.3 步骤二）

def cmd_preflight(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    root: Path = ctx.root
    checks: list[dict] = []

    def check(name: str, status: str, detail: str, data: dict | None = None) -> None:
        checks.append({"check": name, "status": status, "detail": detail, **(data or {})})

    # 1. 通道与布局
    layout = detect_channel_layout(root)
    check("通道与布局探测", "ok" if layout["ok"] else "fail",
          f"通道 {layout['channel']} / 模式 {layout['mode']}：" + "；".join(layout["detail"]),
          {"channel": layout["channel"], "mode": layout["mode"]})
    # 2. 本地 VERSION
    local_raw = None
    try:
        local_raw = read_local_version(root)
        parse_semver(local_raw)
        check("本地 VERSION", "ok", f"VERSION={local_raw}")
    except Exception as exc:
        check("本地 VERSION", "fail", f"不可读或不合法：{exc}")
    # 3. manifest（未给 --target/--manifest 时记 skipped，agent 可补参重跑）
    manifest = None
    if ctx.target or ctx.manifest:
        try:
            manifest, source = load_manifest(ctx.target, ctx.manifest)
            issues = validate_manifest(manifest)
            if issues:
                check("目标 manifest", "fail", "未过 6.2 字段校验：" + "；".join(issues))
                manifest = None
            else:
                check("目标 manifest", "ok", f"version={manifest['version']}（{source}）")
        except UpgradeError as exc:
            check("目标 manifest", "fail", str(exc))
    else:
        check("目标 manifest", "skipped", "未指定 --target/--manifest——版本方向与金丝雀判定未跑，agent 补参重跑本步")
    # 4. 版本方向
    if manifest and local_raw:
        local, target = parse_semver(local_raw), parse_semver(manifest["version"])
        min_from = parse_semver(manifest["min_upgradable_from"])
        if semver_cmp(target, local) <= 0:
            check("版本方向", "fail", f"目标 {manifest['version']} 不高于本地 {local_raw}")
        elif semver_cmp(local, min_from) < 0:
            check("版本方向", "fail",
                  f"本地 {local_raw} 低于 min_upgradable_from={manifest['min_upgradable_from']}"
                  f"（先跑 plan 看中间版本清单）")
        else:
            check("版本方向", "ok", f"{local_raw} → {manifest['version']}")
    # 5. 磁盘余量（构成式）
    snap_parts = snapshot_objects_size(root)
    snap_total = sum(snap_parts.values())
    code_size = code_size_estimate(root)
    staging = root.parent / "upgrade" / f"staging-{manifest['version']}" if manifest else None
    staging_size = _dir_size(staging) if staging and staging.is_dir() else None
    need_parts = {"快照对象": snap_total}
    if layout["channel"] == "Z":
        need_parts["新版解包(近似)"] = staging_size if staging_size is not None else code_size
        need_parts["prev旧代码"] = code_size
    need = sum(need_parts.values())
    need_with_margin = int(need * 1.1)
    volume_path = root.parent if (layout["channel"] == "Z" or layout["mode"] == "B") else root
    free = shutil.disk_usage(volume_path).free
    disk_ok = free >= need_with_margin
    check("磁盘余量(构成式)", "ok" if disk_ok else "fail",
          f"需 {need_with_margin/1024/1024:.0f} MB（构成 " +
          " + ".join(f"{k}:{v/1024/1024:.0f}MB" for k, v in need_parts.items()) +
          " + 10% 余量）vs 卷 " + str(volume_path) + f" 可用 {free/1024/1024:.0f} MB" +
          ("" if staging_size is not None or layout["channel"] == "G"
           else "；新版体积以当前代码近似（staging 未解包）"),
          {"need_bytes": need_with_margin, "free_bytes": free,
           "parts": {k: v for k, v in need_parts.items()},
           "snapshot_parts": snap_parts})
    # 6. staging 同卷（通道 Z 专属）
    if layout["channel"] == "Z":
        same = os.stat(root).st_dev == os.stat(root.parent).st_dev
        check("升级工作区同卷", "ok" if same else "fail",
              f"{root} 与 {root.parent / 'upgrade'} 的 st_dev "
              f"{'一致' if same else '不一致——跨卷 rename 不可行（3.1）'}")
    else:
        check("升级工作区同卷", "skipped", "通道 G 无 staging 份额")
    # 7. 门户端口
    port = probe_port_8620()
    if port["listening"]:
        check("门户端口 8620", "warn",
              f"门户在运行（PID={port['pid']}）——无监听为佳；真杀留给停机步骤")
    else:
        check("门户端口 8620", "ok", "无监听")
    # 8. D11 定时开关
    sched = schedule_d11_state(root)
    check("D11 定时开关状态",
          "warn" if sched.get("schedule_enabled") else "ok",
          sched["note"], sched)
    # 9. 备份目标可写（经 data_dir 定位：模式 B 落产品根平级 data/backup）
    ok_w, where = backup_target_writable(root, layout)
    check("备份目标可写", "ok" if ok_w else "fail", where if ok_w else where)
    # 10. 无未完成升级
    state = read_state(root)
    in_progress = (state or {}).get("in_progress") if isinstance(state, dict) else state
    if state is None:
        check("无未完成升级", "ok", "state.json 不存在（未执行过协议步骤）")
    elif isinstance(state, dict) and state.get("corrupt"):
        check("无未完成升级", "fail", state["note"])
    elif in_progress:
        check("无未完成升级", "fail", f"存在未完成升级：{json.dumps(in_progress, ensure_ascii=False)}")
    else:
        check("无未完成升级", "ok", "in_progress 为空")
    # 11. 下一轮补齐（明确 deferred，不冒充通过）
    check("无跑批进行中", "deferred", "dbt_runner 状态与存活进程检查随停机窗四步下一轮实现")
    check("备份速率标定", "deferred", "100MB 试块标定随 backup 内部逻辑下一轮实现；"
          "未标定时窗口预估按每 GB 一分钟保守估（3.3）")

    lines = [f"[preflight] 通道 {layout['channel']} / 模式 {layout['mode']}"]
    icon = {"ok": "✅", "warn": "⚠️ ", "fail": "❌", "skipped": "⏭️ ", "deferred": "⏳"}
    for c in checks:
        lines.append(f"  {icon[c['status']]} {c['check']}：{c['detail']}")
    failed = [c for c in checks if c["status"] == "fail"]
    overall = "fail" if failed else "ok"
    lines.append(f"[preflight] 结论：{'未过项 ' + str(len(failed)) + ' 条，exit 1' if failed else '通过（exit 0）'}")
    return (1 if failed else 0), overall, lines, {
        "checks": checks, "channel": layout["channel"], "mode": layout["mode"],
        "local_version": local_raw,
        "failed_checks": [c["check"] for c in failed]}


# ---------------------------------------------------------------- 停机窗公共件

def _state_file_for(root: Path, staging: Path | None = None) -> Path:
    """状态文件多址探测：data/ 搬迁前在 root/data、搬迁后在 staging/data（3.3：
    状态机随 data/ 整体搬迁）；模式 B 恒在产品根平级 data/。staging 未指明时扫
    upgrade/staging-v*（migrate 续跑时 data 已搬、目标 staging 名要从状态里读的
    鸡生蛋问题靠这个扫解）。探测不到时返回 root 侧默认位（由调用方创建）。"""
    candidates = [root / "data" / "upgrade" / "state.json"]
    if staging is not None:
        candidates.append(staging / "data" / "upgrade" / "state.json")
    else:
        ups = root.parent / "upgrade"
        if ups.is_dir():
            candidates += [s / "data" / "upgrade" / "state.json"
                           for s in sorted(ups.glob("staging-v*"))]
    candidates.append(root.parent / "data" / "upgrade" / "state.json")  # 模式 B 平级兜底
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


def _load_json_file(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_json_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def kill_portal_8620() -> list[str]:
    """手册 P-01 / R-07 同款（ops/launcher.py kill_port 逻辑）：netstat 找 8620
    LISTENING 的全部 PID，taskkill /F 逐一结束。返回被杀 PID 列表。"""
    try:
        raw = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=15).stdout
    except Exception:
        return []
    out = raw.decode("utf-8", errors="ignore")  # 只匹配 ASCII 片段，容忍任意代码页
    pids: list[str] = []
    for line in out.splitlines():
        if ":8620" in line and "LISTENING" in line.upper():
            pid = line.split()[-1]
            if pid not in pids:
                pids.append(pid)
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=15)
    return pids


def warehouse_lock_probe(root: Path) -> tuple[bool, list[dict]]:
    """「复查无跑批」的效应级检查：跑批中的 dbt 持有金库写锁，只读连接必败
    （dbt_runner 的运行态在内存、无磁盘标记可查，app/services/dbt_runner.py:23）。
    stop 由旧根 venv 执行，duckdb 允许 lazy import（不进 py -3 路径）。"""
    wh = data_dir(root) / "warehouse"
    dbs = sorted(wh.glob("*.duckdb")) if wh.is_dir() else []
    if not dbs:
        return True, [{"path": None, "ok": True, "note": "无金库（新装属正常）"}]
    try:
        import duckdb  # lazy import：本函数只被 venv 执行的子命令调用
    except Exception as exc:
        return False, [{"path": None, "ok": False, "note": f"duckdb 导入失败：{exc}（venv 损坏？）"}]
    results, all_ok = [], True
    for db in dbs:
        ok, note = False, ""
        for _ in range(3):
            try:
                con = duckdb.connect(str(db), read_only=True)
                con.execute("select 1").fetchall()
                con.close()
                ok, note = True, "可只读打开（无写锁占用）"
                break
            except Exception as exc:
                note = str(exc).splitlines()[0] if str(exc) else repr(exc)
                time.sleep(1)
        results.append({"path": str(db), "ok": ok, "note": note})
        all_ok = all_ok and ok
    return all_ok, results


def _under(path: Path, ancestor: Path) -> bool:
    """path 是否等于或在 ancestor 之内（3.8 兼容写法——is_relative_to 是 3.9+）。"""
    try:
        path.relative_to(ancestor)
        return True
    except ValueError:
        return False


def _tree_bytes(path: Path, exclude: Path | None = None) -> int:
    """对账口径（3.2）：rename 不重读字节，对账只查元数据——目录取递归文件字节数，
    文件取 st_size。exclude 指定的子树不计（见 _item_bytes 口径注）。"""
    if exclude is not None and _under(path, exclude):
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for d, dirnames, filenames in os.walk(path):
        if exclude is not None:
            dirnames[:] = [n for n in dirnames if not _under(Path(d) / n, exclude)]
        for fn in filenames:
            try:
                total += (Path(d) / fn).stat().st_size
            except OSError:
                pass
    return total


def _item_bytes(base: Path, item: dict) -> int:
    """搬迁项字节数：base 为 root（搬前）或 staging（搬后）。口径注：data/ 项排除
    data/upgrade/ 子树——状态文件自身在 data/ 内，把它的字节数写进存在 data/ 里的
    意图清单是自指（写意图即改 data/ 字节数，永远对不上账）；协议状态区的漂移由
    状态机 history 记录，不参与字节冻结。其余项不排除。"""
    p = base / item["rel"]
    excl = base / item["exclude"] if item.get("exclude") else None
    return _tree_bytes(p, excl)


# ---------------------------------------------------------------- 子命令：stop（3.3 步骤四）

def cmd_stop(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """停机：杀 8620（P-01 逻辑）→ 复查端口已空 → 金库写锁复查（=无跑批复查）。
    全过后置 in_progress——升级窗口从此开（3.4：此后步骤默认须人类点头）。"""
    root: Path = ctx.root
    layout = detect_channel_layout(root)
    if not layout["ok"]:
        raise UpgradeError("；".join(layout["detail"]))
    state_file = state_path(root)
    state = _load_json_file(state_file) or {}
    last_plan = state.get("last_plan") if isinstance(state, dict) else None
    if not last_plan:
        raise UpgradeError("状态机无 last_plan——先跑 plan 记录目标版本与 manifest"
                           "（协议顺序 plan→preflight→stage→stop；stop/backup 命令面无参，目标只能经状态机传递）")
    try:
        local_raw = read_local_version(root)
        parse_semver(local_raw)
    except Exception as exc:
        raise UpgradeError(f"本地 VERSION 不可读或不合法：{exc}")
    target = last_plan.get("target")
    if not target:
        raise UpgradeError("last_plan 缺 target——重跑 plan")

    lines: list[str] = []
    killed = kill_portal_8620()
    lines.append(f"[stop] 门户 8620：{'已结束占用进程 ' + '、'.join(killed) if killed else '本无监听'}")
    port = probe_port_8620()
    if port["listening"]:
        raise UpgradeError(f"杀进程后 8620 仍有监听（PID={port['pid']}）——人工处置后重跑 stop")
    lines.append("[stop] 复查：8620 无监听 ✅")
    lock_ok, lock_details = warehouse_lock_probe(root)
    for r in lock_details:
        shown = r["path"] or "（无金库）"
        try:
            shown = Path(shown).relative_to(root).as_posix()
        except (ValueError, TypeError):
            pass
        lines.append(f"  {'✅' if r['ok'] else '❌'} 写锁复查 {shown}：{r['note']}")
    if not lock_ok:
        raise UpgradeError("金库写锁复查未过——疑似跑批进行中（写锁持有），等跑完重跑 stop（3.3 步骤四）")

    prog = state.get("in_progress") or {}
    prog.update({"started_at": now_iso(), "channel": layout["channel"],
                 "mode": layout["mode"], "from": local_raw, "target": target,
                 "steps": ["stop"]})
    state["in_progress"] = prog
    state["format"] = "clearledger-upgrade-state/1"
    if state.pop("migrate", None) is not None:
        # 演练缺陷2：上一轮回滚不清 migrate 意图（done 态残留）会让下一轮 migrate
        # 「沿用意图」跳过全部搬迁、终对账撞死。开新窗即清——新窗口新意图。
        lines.append("[stop] 已清除上一轮搬迁意图（state.migrate）——新窗口按当前实况重建意图")
    _save_json_file(state_file, state)
    lines.append(f"[stop] 停机完成：升级窗口已开（{local_raw} → {target}，in_progress 已置位）")
    return 0, "ok", lines, {"killed_pids": killed, "lock_probe": lock_details,
                            "from": local_raw, "target": target}


# ---------------------------------------------------------------- 子命令：backup（3.3 步骤五）

def cmd_backup(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """备份硬闸门（R1）：调 ops/backup.py --tag pre-upgrade-<旧>-<新>（同一实现）；
    校验快照目录与 backup_manifest 三字段指纹（回滚判定依据）；通道 G 记升级前
    HEAD。哨兵基线采集（步骤五第 4 项）随 canary 批次实现，显式记 deferred。"""
    root: Path = ctx.root
    state_file = state_path(root)
    state = _load_json_file(state_file) or {}
    prog = state.get("in_progress") if isinstance(state, dict) else None
    if not prog:
        raise UpgradeError("无 in_progress——先跑 stop（协议顺序 stop→backup）")
    try:
        local_raw = read_local_version(root)
    except Exception as exc:
        raise UpgradeError(f"本地 VERSION 不可读：{exc}")
    target = prog.get("target") or (state.get("last_plan") or {}).get("target")
    if not target:
        raise UpgradeError("状态机缺目标版本——重跑 plan")

    tag = f"pre-upgrade-{local_raw}-{target}"
    backup_py = Path(__file__).resolve().parent / "backup.py"
    if not backup_py.is_file():
        raise UpgradeError(f"找不到 {backup_py}——升级包不完整（backup.py 是落点 8 的共享实现）")
    lines = [f"[backup] 快照：{tag}（复用 ops/backup.py 同一实现，含 sha256/size/mtime 指纹）"]
    proc = subprocess.run([sys.executable, str(backup_py), "--root", str(root),
                           "--tag", tag], capture_output=True, timeout=1800)
    out = (proc.stdout or b"").decode("utf-8", errors="replace")
    err = (proc.stderr or b"").decode("utf-8", errors="replace")
    lines.extend(f"  {ln}" for ln in out.splitlines()[-6:])  # 中转尾部摘要，全量见快照侧输出
    if err.strip():
        lines.append(f"  [backup.py stderr] {err.strip().splitlines()[-1]}")
    if proc.returncode != 0:
        raise UpgradeError(f"ops/backup.py 退出码 {proc.returncode}——快照未过即硬闸门失败（R1），"
                           f"停机窗口就此中止：重启门户恢复运行，旧版本原样（3.3 步骤五）")

    broot = data_dir(root) / "backup"
    cands = sorted((p for p in broot.glob(tag + "*") if p.is_dir()),
                   key=lambda p: p.stat().st_mtime)
    if not cands:
        raise UpgradeError(f"backup.py 退出 0 但找不到快照目录：{broot / (tag + '*')}")
    snap = cands[-1]
    mpath = snap / "backup_manifest.json"
    bmanifest = _load_json_file(mpath)
    if not isinstance(bmanifest, dict) or not bmanifest.get("files"):
        raise UpgradeError(f"快照清单缺失或为空：{mpath}")
    duck = [f for f in bmanifest["files"]
            if f["path"].startswith("data/warehouse/") and f["path"].endswith(".duckdb")]
    bad = [f.get("path", "?") for f in duck
           if not (isinstance(f.get("sha256"), str) and isinstance(f.get("size"), int)
                   and isinstance(f.get("mtime"), (int, float)))]
    if not duck or bad:
        raise UpgradeError("快照 manifest 未含每个金库的 sha256/size/mtime 三字段"
                           f"（回滚判定依据，3.3 步骤五第 2 项）：{'；'.join(bad) or '无 duckdb 条目'}")
    totals = bmanifest.get("totals", {})
    lines.append(f"[backup] 快照落位：{snap.name}"
                 f"（{len(bmanifest['files'])} 文件 / {totals.get('bytes', 0) / 1024 / 1024:.1f} MB / 金库 {len(duck)} 个）")

    git_head = None
    if detect_channel_layout(root)["channel"] == "G":
        try:
            git_head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                      capture_output=True, timeout=30).stdout.decode().strip()
        except Exception as exc:
            raise UpgradeError(f"通道 G 记录升级前 HEAD 失败：{exc}")
        if not git_head:
            raise UpgradeError("通道 G 记录升级前 HEAD 失败：rev-parse 输出为空")
        lines.append(f"[backup] 通道 G：升级前 HEAD={git_head[:12]}（回滚用）")
    # 哨兵基线采集（3.3 步骤五第 4 项：此刻门户已停、无跑批，基线与快照必然一致；
    # 清单来自目标版 manifest、基线由旧代码产出，两侧版本不同是设计使然）
    reports = (state.get("last_plan") or {}).get("manifest", {}).get("sentinel_reports", [])
    baseline, base_ok = _collect_sentinel_baseline(root, reports,
                                                   (state.get("last_plan") or {}).get("manifest", {}).get("tenants_builtin", []))
    for rep, rec in sorted(baseline.get("reports", {}).items()):
        lines.append(f"  [{'✅' if rec['status'] in ('ok', 'skip') else '❌'}] 哨兵基线[{rep}]：{rec['status']}"
                     + (f"（{rec.get('note', '')[:80]}）" if rec.get("note") else ""))
    if not base_ok:
        raise UpgradeError("哨兵基线采集未过（通过条件：清单内报表全部采集成功，步骤五第 4 项）"
                           "——停机窗口就此中止，重启门户恢复运行")

    prog["steps"] = (prog.get("steps") or []) + ["backup"]
    prog["backup"] = {"at": now_iso(), "snapshot_dir": str(snap), "manifest": str(mpath),
                      "files": len(bmanifest["files"]), "bytes": totals.get("bytes"),
                      "duckdb_count": len(duck), "git_head": git_head,
                      "sentinel_baseline": baseline}
    state["in_progress"] = prog
    _save_json_file(state_file, state)
    return 0, "ok", lines, {"snapshot_dir": str(snap), "tag": tag, "git_head": git_head}


# ---------------------------------------------------------------- 子命令：migrate（3.2 + 3.3 步骤六 6A，纯标准库）

def _build_migrate_intent(root: Path, tenants_builtin: list[str]) -> tuple[list[dict], list[str]]:
    """3.2 持久资产搬迁清单展开（仅通道 Z 且模式 A）。意图项含 rel/kind/mandatory/
    bytes（源在时实测）。可选项源目标皆缺记入跳过说明；必选项（data、.venv）即使
    皆缺也保留为条目——执行时按「两者皆缺计该项失败」处置（3.3 步骤六 6A）。"""
    items: list[dict] = []
    skipped: list[str] = []

    def add(rel: str, kind: str, mandatory: bool) -> None:
        src = root / rel
        exclude = "data/upgrade" if rel == "data" else None  # 口径注见 _item_bytes
        if src.exists():
            items.append({"rel": rel, "kind": kind, "mandatory": mandatory,
                          "exclude": exclude,
                          "bytes": _item_bytes(root, {"rel": rel, "exclude": exclude}),
                          "status": "pending"})
        elif mandatory:
            items.append({"rel": rel, "kind": kind, "mandatory": True,
                          "exclude": exclude, "bytes": None, "status": "pending"})  # 执行时按「两者皆缺」失败
        else:
            skipped.append(f"{rel}（源不存在，可选项）")

    # 3.2 清单顺序：data → .venv → logs → exe → 真实账套整目录 → builtin 的 data/onboarding
    add("data", "dir", True)
    add(".venv", "dir", True)
    add("logs", "dir", False)
    add("启动明账.exe", "file", False)
    add("ClearLedger-Launcher.exe", "file", False)
    inst_root = root / "instances"
    if inst_root.is_dir():
        real, builtin_present = [], [n for n in tenants_builtin if (inst_root / n).is_dir()]
        for d in sorted(inst_root.iterdir()):
            if d.is_dir() and (d / "instance.yml").exists() and d.name not in tenants_builtin:
                real.append(d.name)
        for name in real:  # 真实账套 = 本地存在而 tenants_builtin 清单没有（3.2 第 5 项）
            add(f"instances/{name}", "dir", False)
        for name in sorted(builtin_present):  # builtin 只搬本地资产子目录（3.2 第 6 项）
            add(f"instances/{name}/data", "dir", False)
            add(f"instances/{name}/onboarding", "dir", False)
    return items, skipped


def cmd_migrate(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """搬迁（py -3 执行，纯标准库）：先写意图再逐项同卷 rename；三态判定幂等可重入；
    失败出口二选一——重跑续跑 或 --revert 逆向搬回（3.3 步骤六 6A）。"""
    root: Path = ctx.root
    if (root / ".git").exists():
        raise UpgradeError("通道 G 无 migrate——版本移动走 sync（3.3 步骤六 6B）")
    state_file = _state_file_for(root)  # 多址探测：data 已搬时状态在 staging 侧
    state = _load_json_file(state_file)
    if not isinstance(state, dict):
        raise UpgradeError(f"状态机不可读：{state_file}——人工核查（migrate 不得在状态不明时动目录）")
    prog = state.get("in_progress")
    if not prog:
        raise UpgradeError("无 in_progress——按序先跑 stop→backup（搬迁不得提前到停机之前，3.2）")
    if not prog.get("backup"):
        raise UpgradeError("硬闸门 R1：状态机无 backup 记录——快照未过，后续任何步骤不得执行（3.3 步骤五）")
    target = prog.get("target") or (state.get("last_plan") or {}).get("target")
    if not target:
        raise UpgradeError("状态机缺目标版本——重跑 plan")
    staging = root.parent / "upgrade" / f"staging-{target}"
    if not staging.is_dir():
        raise UpgradeError(f"staging 不存在：{staging}——先跑 stage（3.3 步骤三）")
    if os.stat(root).st_dev != os.stat(staging).st_dev:
        raise UpgradeError(f"产品根与 staging 跨卷（st_dev 不同）——同卷 rename 不可行（3.1；preflight 应已拦住）")
    mode = window_mode(root, staging)  # 窗口中段视角：data 已搬入 staging 是合法中间态
    if mode == "unknown":
        raise UpgradeError("布局探测不明且非窗口中间态（instances/ 与 data/ 只有一个在、staging 侧也无 data）"
                           "——按 3.1 禁止猜，人工核查")
    if mode == "B":
        raise UpgradeError("模式 B（持久资产在产品根外）无搬迁项——直接 switch（开放问题 4 的退化形态；"
                           "该分支的放开需在真实模式 B 环境实测后确认）")
    tenants = (state.get("last_plan") or {}).get("manifest", {}).get("tenants_builtin", [])
    lines: list[str] = [f"[migrate] staging={staging.name}｜通道 Z / 模式 {mode}｜同卷 ✅"]

    if ctx.revert:
        return _migrate_revert(root, staging, state, lines)

    mig = state.get("migrate") if isinstance(state.get("migrate"), dict) else {}
    intent = mig.get("intent")
    # 演练缺陷2（防残留）：沿用意图前校验 done 项确在当前 staging 侧——上一轮回滚
    # 残留的 done 意图对不上新 staging，沿用会跳过全部搬迁并在终对账撞死。
    stale_done = [it for it in (intent or [])
                  if it.get("status") == "done" and not (staging / it["rel"]).exists()]
    if isinstance(intent, list) and intent and not stale_done:
        lines.append(f"[migrate] 沿用已存搬迁意图（{len(intent)} 项）——幂等续跑（3.3 步骤六 6A）")
    else:
        if stale_done:
            lines.append(f"[migrate] 已存意图含 {len(stale_done)} 项 done 但不在当前 staging"
                         f"（{'、'.join(i['rel'] for i in stale_done[:3])}…）——判定为残留，按当前实况重建意图")
        intent, skipped = _build_migrate_intent(root, tenants)
        state["migrate"] = {"intent": intent, "skipped": skipped, "built_at": now_iso()}
        _save_json_file(_state_file_for(root, staging), state)  # 先写意图再动目录
        lines.append(f"[migrate] 搬迁意图已写状态机（{len(intent)} 项，跳过 {len(skipped)} 项）")
        for s in skipped:
            lines.append(f"  [跳过] {s}")

    failed = None
    for it in intent:
        if it.get("status") == "done":
            lines.append(f"  [已搬过] {it['rel']}（意图标记 done）")
            continue
        rel = it["rel"]
        src, dst = root / rel, staging / rel
        src_in, dst_in = src.exists(), dst.exists()
        if src_in and not dst_in:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)  # staging 可能缺 instances/ 等父目录
                os.rename(src, dst)
            except OSError as exc:
                it.update(status="failed", error=f"rename 失败：{exc}")
                failed = it
                break
            got = _item_bytes(staging, it)
            if it.get("bytes") is not None and got != it["bytes"]:
                it.update(status="failed", error=f"搬后字节数不符（记 {it['bytes']}，实测 {got}）")
                failed = it
                break
            it["status"] = "done"
            lines.append(f"  [OK] {rel}（{it['bytes']:,} 字节 rename）")
        elif not src_in and dst_in:
            got = _item_bytes(staging, it)
            if it.get("bytes") is not None and got == it["bytes"]:
                it["status"] = "done"
                lines.append(f"  [已搬过] {rel}（对账一致——上次已搬，续跑）")
            else:
                it.update(status="failed",
                          error=f"目标在但字节数不符（记 {it.get('bytes')}，实测 {got}）——人工分诊")
                failed = it
                break
        elif not src_in and not dst_in:
            it.update(status="failed",
                      error="源与目标皆缺" + ("（必选项，3.2 清单第 1/2 项）" if it.get("mandatory") else ""))
            failed = it
            break
        else:
            it.update(status="failed", error="源与目标并存（半搬或外部写入）——人工分诊")
            failed = it
            break

    state.setdefault("migrate", {})["intent"] = intent
    if failed is not None:
        state["migrate"]["last_error"] = f"{failed['rel']}: {failed['error']}"
        _save_json_file(_state_file_for(root, staging), state)
        lines.append(f"[migrate] 单项失败即停（3.3 步骤六 6A）：{failed['rel']}——{failed['error']}")
        lines.append("[migrate] 失败出口二选一：重跑 migrate 幂等续跑；或 migrate --revert 逆向搬回已搬项")
        return 1, "fail", lines, {"failed_item": failed, "intent": intent}

    # 终对账：全部 done 且存在+字节数一致
    for it in intent:
        dst = staging / it["rel"]
        if not dst.exists() or (it.get("bytes") is not None and _item_bytes(staging, it) != it["bytes"]):
            _save_json_file(_state_file_for(root, staging), state)
            raise UpgradeError(f"终对账未过：{it['rel']}（staging 侧存在或字节数不符）")
    prog["steps"] = (prog.get("steps") or []) + ["migrate"]
    prog["migrate"] = {"at": now_iso(), "items": len(intent),
                       "bytes_total": sum(i.get("bytes") or 0 for i in intent)}
    state["in_progress"] = prog
    _save_json_file(_state_file_for(root, staging), state)  # data 已搬——状态文件随 data 走
    lines.append(f"[migrate] 清单全部到达已搬过态且对账全过（{len(intent)} 项，"
                 f"{prog['migrate']['bytes_total'] / 1024 / 1024:.1f} MB）——状态文件已随 data/ 迁至 staging")
    return 0, "ok", lines, {"items": len(intent), "intent": intent}


def _migrate_revert(root: Path, staging: Path, state: dict,
                    lines: list[str]) -> tuple[int, str, list[str], dict]:
    """--revert：按 state.json 意图清单逆向 rename 回旧根并复对账（整体退回停机前，
    归位后重启门户即恢复运行）。逆序回搬——后搬的先回，避免父目录占用。"""
    intent = (state.get("migrate") or {}).get("intent")
    if not isinstance(intent, list) or not intent:
        raise UpgradeError("状态机无搬迁意图——无可回搬（先跑过一次 migrate）")
    lines.append("[migrate] --revert：按意图清单逆向搬回旧根（3.3 步骤六 6A 失败出口之二）")
    failed = None
    for it in reversed(intent):
        if it.get("status") != "done":
            continue
        rel = it["rel"]
        src, dst = root / rel, staging / rel
        if src.exists() or not dst.exists():
            it.update(status="failed", error=f"回搬态异常（旧根侧在={src.exists()}，staging 侧在={dst.exists()}）")
            failed = it
            break
        try:
            src.parent.mkdir(parents=True, exist_ok=True)
            os.rename(dst, src)
        except OSError as exc:
            it.update(status="failed", error=f"回搬 rename 失败：{exc}")
            failed = it
            break
        got = _item_bytes(root, it)
        if it.get("bytes") is not None and got != it["bytes"]:
            it.update(status="failed", error=f"回搬后字节数不符（记 {it['bytes']}，实测 {got}）")
            failed = it
            break
        it["status"] = "reverted"
        lines.append(f"  [回搬] {rel}")
    state.setdefault("migrate", {})["intent"] = intent
    if failed is None:
        for it in intent:  # 复对账：done 全部清零
            if it.get("status") == "done":
                failed = it
                it.update(status="failed", error="回搬后仍有 done 态残留")
                break
    _save_json_file(_state_file_for(root, staging), state)  # data 已回旧根——状态文件跟回
    if failed is not None:
        lines.append(f"[migrate] --revert 失败：{failed['rel']}——{failed['error']}；已回搬项留在旧根，人工按手册 R-14 处置")
        return 1, "fail", lines, {"failed_item": failed}
    lines.append("[migrate] --revert 完成：全部已搬项归位旧根并复对账——重启门户即恢复运行")
    return 0, "ok", lines, {"reverted": sum(1 for i in intent if i.get("status") == "reverted")}


# ---------------------------------------------------------------- 子命令：switch（3.3 步骤六 6A，纯标准库）

def cmd_switch(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """槽位换名（py -3 执行，纯标准库）：复查门户已停（防竞态）→ rename 旧根到
    upgrade/prev-v<旧版> → rename staging 到产品根 → 后验（VERSION/data/.venv/dbt.exe）。
    失败出口：第一次 rename 失败旧根未动；第二次失败把 prev 改回原名（3.3 步骤六）。"""
    root: Path = ctx.root
    if (root / ".git").exists():
        raise UpgradeError("通道 G 无 switch——版本移动走 sync（3.3 步骤六 6B）")
    ups = root.parent / "upgrade"
    stagings = sorted(ups.glob("staging-v*")) if ups.is_dir() else []
    if not stagings:
        raise UpgradeError(f"{ups} 下无 staging-v*——先跑 stage（旧根未动）")
    if len(stagings) > 1:
        raise UpgradeError(f"多个 staging 并存：{[s.name for s in stagings]}——人工清理后重试（旧根未动）")
    staging = stagings[0]
    mode = window_mode(root, staging)  # 窗口中段视角：migrate 后 data 在 staging 属合法
    if mode == "unknown":
        raise UpgradeError("布局探测不明且非窗口中间态——按 3.1 禁止猜；人工核查（旧根未动）")

    state_file = _state_file_for(root, staging)
    state = _load_json_file(state_file)
    if not isinstance(state, dict):
        raise UpgradeError(f"状态机不可读：{state_file}——人工核查（switch 不得在状态不明时换名）")
    prog = state.get("in_progress")
    if not prog:
        raise UpgradeError("无 in_progress——按序先跑 stop→backup→migrate")
    if not prog.get("backup"):
        raise UpgradeError("硬闸门 R1：状态机无 backup 记录——快照未过，后续任何步骤不得执行（3.3 步骤五）")
    target = prog.get("target")
    if not target:
        raise UpgradeError("状态机缺目标版本——重跑 plan")
    try:
        local_raw = read_local_version(root)
    except Exception as exc:
        raise UpgradeError(f"旧根 VERSION 不可读：{exc}")
    prev = ups / f"prev-{local_raw}"  # local_raw 自带 v 前缀（如 v0.8.0 → prev-v0.8.0，3.1 目录形态）
    lines: list[str] = [f"[switch] {local_raw} → {target}｜staging={staging.name}｜prev={prev.name}"]

    if probe_port_8620()["listening"]:
        raise UpgradeError("门户 8620 在运行——switch 前复查未过（防竞态，3.3 步骤六）；先重跑 stop")
    lines.append("[switch] 复查：门户已停 ✅")
    try:
        staging_ver = (staging / "VERSION").read_text(encoding="utf-8").strip()
    except Exception as exc:
        raise UpgradeError(f"staging 缺 VERSION（{exc}）——stage 静态检查应已拦住；旧根未动")
    if staging_ver != target:
        raise UpgradeError(f"staging VERSION={staging_ver} 与目标 {target} 不符——旧根未动")
    if prev.exists():
        raise UpgradeError(f"{prev} 已存在——防覆盖（prev 是回滚槽位），人工处置后重试；旧根未动")
    if mode == "A" and (root / "data").exists():
        raise UpgradeError("data/ 仍在旧根——先跑 migrate（3.2：搬迁漏项会让持久资产困进 prev）")

    try:
        os.rename(root, prev)
    except OSError as exc:
        raise UpgradeError(f"第一次 rename 失败（旧根未动）：{exc}")
    lines.append(f"[switch] rename 1/2：旧根 → {prev.name} ✅")
    try:
        os.rename(staging, root)
    except OSError as exc:
        try:
            os.rename(prev, root)
        except OSError as exc2:
            raise UpgradeError(f"第二次 rename 失败（{exc}）且回滚 rename 也失败（{exc2}）——"
                               f"人工介入：把 {prev} 改回 {root} 即恢复运行")
        raise UpgradeError(f"第二次 rename 失败：{exc}——prev 已改回原名，旧根恢复运行能力，"
                           f"重启门户即恢复（3.3 步骤六失败出口）")
    lines.append("[switch] rename 2/2：staging → 产品根 ✅")

    # 后验（3.3 步骤六通过条件）
    post_fail = []
    try:
        new_ver = read_local_version(root)
    except Exception as exc:
        new_ver, post_fail = None, post_fail + [f"新根 VERSION 不可读：{exc}"]
    if new_ver is not None and new_ver != target:
        post_fail.append(f"新根 VERSION={new_ver} ≠ 目标 {target}")
    if mode == "A" and not (root / "data").is_dir():
        post_fail.append("新根缺 data/（migrate 搬迁未到位？）")
    dbt = root / ".venv" / "Scripts" / "dbt.exe"
    if not (dbt.is_file() and dbt.stat().st_size > 0):
        post_fail.append(f"新根 {dbt.relative_to(root).as_posix()} 缺失或为空（console_scripts 失效）")
    if post_fail:
        lines.append(f"[switch] 换名完成但后验未过：{'；'.join(post_fail)}")
        lines.append("[switch] 此形态走 rollback（后续批次实现）或人工按手册 R-14——回滚窗口仍开着")
        return 1, "fail", lines, {"post_fail": post_fail, "prev_dir": str(prev)}
    lines.append(f"[switch] 后验全过：VERSION={new_ver}｜data/ 与 .venv/dbt.exe 就位（规范路径恢复，"
                 f"venv 内绝对路径重新有效）")

    # 状态机更新：换名后 state 文件随 data/ 回到产品根（模式 A）或本就在平级（模式 B）
    state2 = _load_json_file(state_path(root))
    state2 = state2 if isinstance(state2, dict) else state
    prog2 = state2.get("in_progress") or prog
    prog2["steps"] = (prog2.get("steps") or []) + ["switch"]
    prog2["switch"] = {"from": local_raw, "to": new_ver, "at": now_iso(), "prev_dir": str(prev)}
    state2["in_progress"] = prog2
    try:
        write_state(root, state2)
    except Exception as exc:
        lines.append(f"[switch] 警告：状态机更新失败（{exc}）——换名已完成不受影响，"
                     f"但 data/upgrade/state.json 需人工检查")
    return 0, "ok", lines, {"from": local_raw, "to": new_ver, "prev_dir": str(prev)}


# ---------------------------------------------------------------- 子命令：prune（3.3 步骤十一，通道 Z）

def cmd_prune(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """收尾收敛（两通道共用，B3：通道 G 不再被拒）：通道 Z 收敛 prev 到最近两代
    （严格匹配 prev-vX.Y.Z 才删）；两通道都列示升级快照（只列不删）并关闭回滚窗口
    （prune 是窗口关闭点——目标 1「每步一条命令」，通道 G 不留手工关窗缺口）。"""
    root: Path = ctx.root
    channel = detect_channel_layout(root)["channel"]
    ups = root.parent / "upgrade"
    lines: list[str] = []
    kept: list[str] = []
    removed: list[str] = []
    if channel == "G":
        lines.append("[prune] 通道 G：无 prev 槽位——跳过 prev 收敛（版本移动走 git，旧代码在历史里）")
    else:
        prevs: list[tuple[tuple[int, int, int], Path]] = []
        if ups.is_dir():
            for p in ups.iterdir():
                m = re.match(r"^prev-v(\d+)\.(\d+)\.(\d+)$", p.name)
                if m and p.is_dir():
                    prevs.append(((int(m.group(1)), int(m.group(2)), int(m.group(3))), p))
        prevs.sort(key=lambda t: t[0], reverse=True)
        kept = [p.name for _v, p in prevs[:2]]
        for _v, p in prevs[2:]:
            shutil.rmtree(p)
            removed.append(p.name)
            lines.append(f"[prune] prev 收敛删除：{p.name}")
        for name in kept:
            lines.append(f"[prune] prev 保留：{name}")
        if not prevs:
            lines.append(f"[prune] {ups} 下无 prev-v* 目录（无可收敛）")

    broot = data_dir(root) / "backup"
    snaps = sorted((p for p in broot.iterdir() if p.is_dir() and p.name.startswith("pre-upgrade-")),
                   key=lambda p: p.name, reverse=True) if broot.is_dir() else []
    kept3, older = snaps[:3], snaps[3:]
    for p in kept3:
        lines.append(f"[prune] 升级快照（保留建议 3 份内）：{p.name}（{_tree_bytes(p) / 1024 / 1024:.1f} MB）")
    for p in older:
        lines.append(f"[prune] 更早快照（只列不删，人确认后手删）：{p.name}（{_tree_bytes(p) / 1024 / 1024:.1f} MB）")
    lines.append(f"[prune] {'prev 收敛 ' + str(len(removed)) + ' 个（保留最近两代）；' if channel == 'Z' else ''}"
                 f"升级快照共 {len(snaps)} 份"
                 f"——prune 永不删快照（3.3 步骤十一；保留上限 3 份属建议值，随开放问题 2 拍板）")
    # 窗口生命周期：prune 是回滚窗口的关闭点（3.3 步骤十可用边界）——收敛成功即清位
    state_file = state_path(root)
    state = _load_json_file(state_file)
    if isinstance(state, dict) and state.get("in_progress"):
        state["in_progress"] = None
        state["window_closed_by"] = {"at": now_iso(), "step": "prune"}
        _save_json_file(state_file, state)
        lines.append("[prune] 回滚窗口关闭：state.in_progress 已清位（prune 后不可再 rollback）")
    return 0, "ok", lines, {"prev_kept": kept, "prev_removed": removed,
                            "snapshots_within_3": [p.name for p in kept3],
                            "snapshots_older": [p.name for p in older]}


# ---------------------------------------------------------------- 哨兵公共件（步骤五/八/九共用）

_NOT_FOUND_HINTS = ("不存在", "未注册", "not found", "No report", "unknown report")


def _pick_sentinel_instance(root: Path, tenants_builtin: list[str]) -> str | None:
    """哨兵/冒烟账套取值（步骤八规则）：真实账套（本地存在且不在 tenants_builtin）
    存在时取真实账套（字典序第一个）；尚未建立时取 settings.json 的 instance。"""
    inst_root = root / "instances"
    real = sorted(d.name for d in inst_root.iterdir()
                  if d.is_dir() and (d / "instance.yml").exists()
                  and d.name not in tenants_builtin) if inst_root.is_dir() else []
    if real:
        return real[0]
    p = data_dir(root) / "settings.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("instance")
    except Exception:
        return None


def _run_query(root: Path, instance: str, report: str) -> tuple[int, str, str]:
    """跑一条 semantic.query（旧根或产品根 venv，cwd=产品根）。返回 (rc, stdout, stderr)。"""
    proc = subprocess.run([sys.executable, "-m", "semantic.query", instance, report],
                          cwd=str(root), capture_output=True, timeout=600)
    return (proc.returncode,
            (proc.stdout or b"").decode("utf-8", errors="replace"),
            (proc.stderr or b"").decode("utf-8", errors="replace"))


def _parse_report_rows(stdout: str) -> list | None:
    """解析 semantic.query 的 JSON 行数组（CLI 只输出 JSON，semantic/query.py:157）。
    解析失败返回 None（比对规则：解析失败计为不一致，步骤八）。"""
    try:
        rows = json.loads(stdout)
    except Exception:
        return None
    return rows if isinstance(rows, list) else None


def _compare_report(baseline_rows: list | None, current_rows: list | None) -> dict:
    """哨兵比对细则（步骤八）：数值单元格精确相等；解析失败、行列数变化计为不一致。
    非数值单元格（维度标签）一并比对——口径变更常先改标签，严格侧更安全。"""
    diffs: list[dict] = []
    if baseline_rows is None or current_rows is None:
        return {"consistent": False, "diffs": [{"kind": "解析失败",
                "note": f"baseline={'可解析' if baseline_rows is not None else '不可解析'}，"
                        f"current={'可解析' if current_rows is not None else '不可解析'}"}]}
    if len(baseline_rows) != len(current_rows):
        diffs.append({"kind": "行数变化", "baseline": len(baseline_rows), "current": len(current_rows)})
    if baseline_rows and current_rows:
        kb, kc = set(baseline_rows[0].keys()), set(current_rows[0].keys())
        if kb != kc:
            diffs.append({"kind": "列集变化", "baseline": sorted(kb), "current": sorted(kc)})
    for i, (b, c) in enumerate(zip(baseline_rows, current_rows)):
        for k in sorted(set(b) & set(c)):
            vb, vc = b[k], c[k]
            if isinstance(vb, bool) or isinstance(vc, bool):
                eq = vb == vc
            elif isinstance(vb, (int, float)) and isinstance(vc, (int, float)):
                eq = vb == vc  # 精确相等（步骤八比对细则）
            else:
                eq = str(vb) == str(vc)
            if not eq:
                diffs.append({"kind": "数值/单元格不一致", "row": i, "cell": k,
                              "baseline": vb, "current": vc})
    return {"consistent": not diffs, "diffs": diffs}


def _collect_sentinel_baseline(root: Path, reports: list[str],
                               tenants_builtin: list[str]) -> tuple[dict, bool]:
    """哨兵基线采集（步骤五第 4 项，backup 时执行——此刻门户已停、无跑批，基线与
    快照必然一致；采集方为旧版本旧代码，两侧版本不同是设计使然）。报表名在旧版
    不存在时记 skip（目标版新增报表，canary 阶段跑通出数即算过，步骤五）。"""
    baseline: dict = {}
    all_ok = True
    if not reports:
        return {"note": "sentinel_reports 为空——本版无哨兵报表", "reports": {}}, True
    instance = _pick_sentinel_instance(root, tenants_builtin)
    if not instance:
        return {"note": "无可用的哨兵账套（无真实账套且 settings 无 instance）", "reports": {}}, False
    for report in reports:
        rc, out, err = _run_query(root, instance, report)
        combined = out + err
        if rc == 0:
            rows = _parse_report_rows(out)
            if rows is None:
                baseline[report] = {"status": "error", "note": "查询成功但输出不可解析为 JSON 行数组"}
                all_ok = False
            else:
                baseline[report] = {"status": "ok", "instance": instance, "rows": rows}
        elif any(h in combined for h in _NOT_FOUND_HINTS):
            baseline[report] = {"status": "skip",
                                "note": "报表名在跑基线的一方（旧版本）不存在——目标版新增，属正常（步骤五）"}
        else:
            baseline[report] = {"status": "error", "note": (err or out).strip().splitlines()[-1] if combined.strip() else f"exit {rc}"}
            all_ok = False
    return {"instance": instance, "reports": baseline}, all_ok


# ---------------------------------------------------------------- 依赖指纹（smoke / rollback 复用）

def _restore_snapshot(root: Path, bmanifest: dict, lines: list[str]) -> bool:
    """情形 B 快照恢复（纯标准库）：逐文件 复制到同目录临时名 → 复制流内算 SHA256 与
    manifest 核对 → 核对通过才 os.replace 落到活路径——恢复介质损坏被检出时绝不
    覆盖现场（步骤十）。路径映射：data/* 经 data_dir 定位（模式 B 平级），其余回产品根。"""
    dd = data_dir(root)
    for entry in bmanifest.get("files", []):
        rel = entry["path"]
        src = Path(bmanifest.get("_snapshot_dir", "")) / rel if bmanifest.get("_snapshot_dir") else None
        # 快照目录由调用方注入（_snapshot_dir），否则按 manifest 同级推断
        if src is None:
            lines.append(f"  [失败] 恢复：manifest 缺快照目录信息（{rel}）")
            return False
        if rel.startswith("data/"):
            dst = dd / rel[len("data/"):]
        else:
            dst = root / rel
        if not src.is_file():
            lines.append(f"  [失败] 恢复：快照侧缺文件 {rel}")
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".restore_tmp")
        digest = hashlib.new("sha256")
        copied = 0
        try:
            with open(src, "rb") as fs, open(tmp, "wb") as fd:
                while True:
                    chunk = fs.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    fd.write(chunk)
                    copied += len(chunk)
        except Exception as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            lines.append(f"  [失败] 恢复复制 {rel}：{exc}——现场保留，禁止继续（步骤十）")
            return False
        if digest.hexdigest() != entry.get("sha256") or copied != entry.get("size"):
            try:
                tmp.unlink()
            except OSError:
                pass
            lines.append(f"  [失败] 恢复介质损坏被检出：{rel}（sha256/size 与 manifest 不符）——"
                         f"现场保留并上报，禁止用损坏介质覆盖（步骤十）")
            return False
        os.replace(tmp, dst)
        lines.append(f"  [恢复] {rel}（{copied:,} 字节，sha256 核对一致）")
    return True

# ---------------------------------------------------------------- 子命令：sync（3.3 步骤六 6B，通道 G）

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=300)


def cmd_sync(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """通道 G 同步（旧根 venv 执行）：fetch --tags → 生成物还原 → 两段 merge →
    通过条件（目标 tag 是 HEAD 祖先 + 无未解决冲突 + 生成物无残留 + 工作树干净）。
    冲突时不自动 abort——输出按登记簿对账指引，对账未完成视作失败（步骤六 6B）。"""
    root: Path = ctx.root
    if not (root / ".git").exists():
        raise UpgradeError("通道 Z 无 sync——版本移动走 migrate+switch（3.3 步骤六 6A）")
    state_file = state_path(root)
    state = _load_json_file(state_file) or {}
    prog = state.get("in_progress") if isinstance(state, dict) else None
    if not prog:
        raise UpgradeError("无 in_progress——按序先跑 stop→backup")
    if not prog.get("backup"):
        raise UpgradeError("硬闸门 R1：状态机无 backup 记录——快照未过，后续任何步骤不得执行（3.3 步骤五）")
    target = prog.get("target") or (state.get("last_plan") or {}).get("target")
    if not target:
        raise UpgradeError("状态机缺目标版本——重跑 plan")
    lines: list[str] = [f"[sync] 通道 G：目标 {target}"]

    r = _git(root, "fetch", "origin", "--tags")
    if r.returncode != 0:
        raise UpgradeError("git fetch origin --tags 失败：" + r.stderr.decode(errors="replace").strip()[:300])
    lines.append("[sync] fetch origin --tags ✅")

    dirty0 = _git(root, "status", "--porcelain").stdout.decode(errors="replace")
    if dirty0.strip():
        for d in root.glob("instances/*/pipeline"):  # 生成物还原（现场脏树两处实证，2.1/6B）
            _git(root, "checkout", "--", d.relative_to(root).as_posix())
        dirty1 = _git(root, "status", "--porcelain").stdout.decode(errors="replace")
        lines.append(f"[sync] 生成物还原已执行（剩余本地改动 {len(dirty1.splitlines())} 处——"
                     f"非生成物的改动须人工处置，sync 不代跑）")
    else:
        lines.append("[sync] 工作树本就干净 ✅")

    r = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if r.returncode != 0:
        raise UpgradeError("读取当前分支失败：" + r.stderr.decode(errors="replace").strip()[:200])
    orig_branch = r.stdout.decode().strip()
    lines.append(f"[sync] 工作分支：{orig_branch}")

    def _merge(branch: str) -> None:
        r = _git(root, "merge", "--no-edit", branch)
        if r.returncode != 0:
            err = r.stderr.decode(errors="replace")
            conflicted = _git(root, "diff", "--name-only", "--diff-filter=U").stdout.decode(errors="replace")
            lines.append(f"[sync] merge {branch} 未完成（对账未完成视作失败，步骤六 6B）")
            if conflicted.strip():
                lines.append("[sync] 冲突文件（现场约定：只可能出现在 HRO-私有改动说明.md 与 instances/）：")
                for f in conflicted.splitlines():
                    lines.append(f"    - {f}")
            lines.append("[sync] 指引：逐条按登记簿（HRO-私有改动说明.md）对账后 add+commit，再重跑 sync 续接；")
            lines.append("[sync] 整体放弃本次认领：git merge --abort 回到升级前 commit，重启门户恢复运行")
            raise _fail(f"merge {branch} 冲突/失败：{err.strip()[:300]}（现场保留，未自动 abort）", lines)

    if orig_branch != "develop":
        r = _git(root, "checkout", "develop")
        if r.returncode != 0:
            raise UpgradeError("checkout develop 失败（本地改动阻塞？）：" +
                               r.stderr.decode(errors="replace").strip()[:300])
        _merge("origin/develop")
        r = _git(root, "checkout", orig_branch)
        if r.returncode != 0:
            raise UpgradeError(f"切回 {orig_branch} 失败：" + r.stderr.decode(errors="replace").strip()[:300])
        _merge("develop")
        lines.append(f"[sync] 两段 merge 完成：develop←origin/develop，{orig_branch}←develop ✅")
    else:
        _merge("origin/develop")
        lines.append("[sync] 单段 merge 完成：develop←origin/develop（工作分支即 develop）✅")

    # 通过条件（6B）：祖先校验（hro 带私有提交，HEAD 必为 merge commit，等值永不成立——用 is-ancestor）
    r = _git(root, "rev-parse", f"{target}^{{commit}}")
    if r.returncode != 0:
        raise UpgradeError(f"目标 tag {target} 不存在（fetch 后仍无）——发版未完成或 tag 名不符")
    tag_commit = r.stdout.decode().strip()
    r = _git(root, "merge-base", "--is-ancestor", tag_commit, "HEAD")
    if r.returncode != 0:
        head = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
        raise UpgradeError(f"通过条件未过：目标 tag {target}（{tag_commit[:12]}）不是 HEAD（{head[:12]}）的祖先")
    lines.append(f"[sync] 祖先校验 ✅：{target} 已包含在 HEAD 历史中")
    unresolved = _git(root, "ls-files", "-u").stdout.decode(errors="replace")
    if unresolved.strip():
        raise UpgradeError("存在未解决冲突（git ls-files -u 非空）——先完成对账")
    lines.append("[sync] 无未解决冲突 ✅")
    leftover = [ln for ln in _git(root, "status", "--porcelain").stdout.decode(errors="replace").splitlines()
                if "instances/" in ln and "/pipeline" in ln]
    if leftover:
        raise UpgradeError("instances/*/pipeline 有残留改动：" + "；".join(leftover[:5]))
    lines.append("[sync] 生成物无残留 ✅")
    dirty = _git(root, "status", "--porcelain").stdout.decode(errors="replace")
    if dirty.strip():
        lines.append(f"[sync] ⚠️ 工作树仍有非生成物改动 {len(dirty.splitlines())} 处（sync 只还原生成物，"
                     f"其余须人工确认）")
    else:
        lines.append("[sync] 工作树干净 ✅")

    head = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    prog["steps"] = (prog.get("steps") or []) + ["sync"]
    prog["sync"] = {"at": now_iso(), "head": head}
    state["in_progress"] = prog
    _save_json_file(state_file, state)
    return 0, "ok", lines, {"head": head, "branch": orig_branch, "target": target}


# ---------------------------------------------------------------- 子命令：canary（3.3 步骤八）

def cmd_canary(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """金丝雀（产品根 venv 执行，版本移动之后——dbt.exe 嵌的规范路径此时重新有效）：
    mart_schema_changed=false 跳过；材料=账套整目录+库文件复制为 _upgrade_test；
    三步链全部 --instance _upgrade_test；哨兵与 backup 采集的基线比对——数值精确
    相等，不一致进 requires_manual_steps 不自动判死（口径变更以 UPGRADE.md 为唯一豁免）。"""
    root: Path = ctx.root
    state_file = state_path(root)
    state = _load_json_file(state_file) or {}
    prog = state.get("in_progress") if isinstance(state, dict) else None
    if not prog:
        raise UpgradeError("无 in_progress——canary 属停机窗步骤（步骤八），按序先跑 stop→backup")
    manifest = (state.get("last_plan") or {}).get("manifest") or {}
    instance = ctx.instance
    lines: list[str] = []

    if not manifest.get("mart_schema_changed"):
        lines.append("[canary] manifest.mart_schema_changed=false——跳过金丝雀（3.3 步骤八）")
        prog["steps"] = (prog.get("steps") or []) + ["canary:skipped"]
        state["in_progress"] = prog
        _save_json_file(state_file, state)
        return 0, "skip", lines, {"skipped": True}

    baseline_rec = (prog.get("backup") or {}).get("sentinel_baseline")
    if not isinstance(baseline_rec, dict) or not baseline_rec.get("reports"):
        raise UpgradeError("哨兵基线缺失——backup 步骤未采集（步骤五第 4 项；manifest 标了 "
                           "mart_schema_changed=true 就必须有基线可比）")
    baseline = baseline_rec["reports"]

    venv_py = root / ".venv" / "Scripts" / "python.exe"
    dbt_exe = root / ".venv" / "Scripts" / "dbt.exe"
    if not (venv_py.is_file() and dbt_exe.is_file()):
        raise UpgradeError("产品根 venv 不完整（缺 python.exe/dbt.exe）——refresh 应已处理")
    src_inst = root / "instances" / instance
    if not (src_inst / "instance.yml").is_file():
        raise UpgradeError(f"账套 {instance} 不存在（instances/{instance}/instance.yml 缺）")

    test_dir = root / "instances" / "_upgrade_test"
    test_db = data_dir(root) / "warehouse" / "_upgrade_test.duckdb"
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)
        lines.append("[canary] ⚠️ 清除上次残留：instances/_upgrade_test")
    if test_db.exists():
        test_db.unlink()
        lines.append("[canary] ⚠️ 清除上次残留：data/warehouse/_upgrade_test.duckdb")
    shutil.copytree(src_inst, test_dir)
    # 副本库指向改写（演练缺陷1）：loader 的 db_path 直取 instance.yml 的 database
    # 字段（semantic/loader.py:102，semantic/query.py 同源），不改写则三步链与哨兵
    # 查询全部读写原库（演练实测 sales.duckdb sha256 被改），与「不触碰原账套原库」
    # 声明相反。database 相对 pipeline/ 目录（实例目录下三级），指向金丝雀副本库。
    inst_yml = test_dir / "instance.yml"
    yml_text = inst_yml.read_text(encoding="utf-8")
    db_line = "database: ../../../data/warehouse/_upgrade_test.duckdb   # canary 副本注入"
    if re.search(r"(?m)^\s*database:\s*\S", yml_text):
        yml_text = re.sub(r"(?m)^\s*database:\s*\S.*?$", db_line, yml_text)
    else:
        yml_text = db_line + "\n" + yml_text
    inst_yml.write_text(yml_text, encoding="utf-8")
    lines.append("[canary] 副本 instance.yml database 已改写 → _upgrade_test.duckdb（三步链与哨兵均落副本库）")
    src_db = data_dir(root) / "warehouse" / f"{instance}.duckdb"
    if not src_db.is_file():
        raise UpgradeError(f"账套库不存在：{src_db}")
    shutil.copy2(src_db, test_db)
    for wal in src_db.parent.glob(src_db.name + ".wal"):
        shutil.copy2(wal, test_db.with_name(test_db.name + ".wal"))
    lines.append(f"[canary] 材料就位：instances/_upgrade_test（复制自 {instance}）+ "
                 f"data/warehouse/_upgrade_test.duckdb（不触碰原账套目录与原库，步骤八）")

    def _chain(step_args: list[str], label: str) -> None:
        r = subprocess.run([str(venv_py), *step_args], cwd=str(root),
                           capture_output=True, timeout=3600)
        tail = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", errors="replace")
        tail_lines = [ln for ln in tail.splitlines() if ln.strip()][-2:]
        lines.append(f"  [{'OK' if r.returncode == 0 else '失败'}] {label}：{' / '.join(tail_lines)[-160:]}")
        if r.returncode != 0:
            lines.append("[canary] 三步链失败——遗骸保留供排查；进步骤十 rollback（步骤八失败出口）")
            raise _fail(f"金丝雀三步链 {label} 失败（exit {r.returncode}）", lines)

    _chain(["-m", "semantic.ingest_run", "--instance", "_upgrade_test"], "ingest")
    _chain(["-m", "semantic.compile_dbt", "--instance", "_upgrade_test"], "compile")
    r = subprocess.run([str(dbt_exe), "build", "--profiles-dir", ".", "--no-use-colors"],
                       cwd=str(test_dir / "pipeline"), capture_output=True, timeout=3600)
    tail = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", errors="replace")
    lines.append(f"  [{'OK' if r.returncode == 0 else '失败'}] dbt build："
                 + " / ".join(ln for ln in tail.splitlines() if ln.strip())[-160:])
    if r.returncode != 0:
        lines.append("[canary] dbt build 未全绿——进步骤十 rollback（步骤八通过条件：dbt build 全绿）")
        raise _fail("金丝雀 dbt build 失败", lines)

    mismatches: list[dict] = []
    for report, base in sorted(baseline.items()):
        rc, out, err = _run_query(root, "_upgrade_test", report)
        current = _parse_report_rows(out) if rc == 0 else None
        if base.get("status") == "skip":
            ok = rc == 0 and isinstance(current, list) and len(current) > 0
            lines.append(f"  {'✅' if ok else '❌'} 哨兵[{report}]：旧版无基线（skip）——"
                         f"{'跑通出数即过（步骤五）' if ok else '在 _upgrade_test 上未跑通出数'}")
            if not ok:
                mismatches.append({"report": report, "kind": "新增报表在 _upgrade_test 未跑通出数",
                                   "detail": (err or out).strip()[-200:]})
            continue
        cmp = _compare_report(base.get("rows"), current)
        if cmp["consistent"]:
            lines.append(f"  ✅ 哨兵[{report}]：与基线一致（数值单元格精确相等）")
        else:
            lines.append(f"  ❌ 哨兵[{report}]：与基线不一致——{cmp['diffs'][:3]}")
            mismatches.append({"report": report, "diffs": cmp["diffs"][:10]})

    if mismatches:
        lines.append("[canary] 哨兵比对不一致 → requires_manual_steps：人工确认（口径变更以 UPGRADE.md "
                     "声明为唯一豁免依据，步骤八）；未确认前不得 finalize，验收不过走 rollback")
        prog["steps"] = (prog.get("steps") or []) + ["canary:requires_manual_steps"]
        prog["canary"] = {"at": now_iso(), "instance": instance, "mismatches": mismatches}
        state["in_progress"] = prog
        _save_json_file(state_file, state)
        return 1, "requires_manual_steps", lines, {"mismatches": mismatches}

    shutil.rmtree(test_dir, ignore_errors=True)
    test_db.unlink(missing_ok=True)
    for wal in test_db.parent.glob(test_db.name + ".wal"):
        wal.unlink()
    lines.append("[canary] 清理 _upgrade_test 完成（smoke 首步会复验，步骤九第 1 项）")
    prog["steps"] = (prog.get("steps") or []) + ["canary"]
    prog["canary"] = {"at": now_iso(), "instance": instance, "result": "pass"}
    state["in_progress"] = prog
    _save_json_file(state_file, state)
    return 0, "ok", lines, {"instance": instance, "reports": sorted(baseline)}


# ---------------------------------------------------------------- 子命令：smoke（3.3 步骤九 + 依赖指纹）

def cmd_smoke(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """门户冒烟（产品根 venv 执行）：①schedule_enabled 记入状态机（步骤十判定输入）
    ②_upgrade_test 清理复验 ③依赖指纹（installed 对 requirements.txt）④doctor
    ⑤launcher --smoke（起门户——schedule_enabled 时会触发 D11 补跑写库，视同情形 B）
    ⑥真实查询 ⑦哨兵比对（只读真库，canary 跳过时的安全网）。"""
    root: Path = ctx.root
    state_file = state_path(root)
    state = _load_json_file(state_file) or {}
    prog = state.get("in_progress") if isinstance(state, dict) else None
    if not prog:
        raise UpgradeError("无 in_progress——smoke 属停机窗步骤（步骤九），状态机缺前置步骤")
    lines: list[str] = []
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str, data: dict | None = None) -> None:
        checks.append({"check": name, "status": "ok" if ok else "fail", "detail": detail, **(data or {})})
        lines.append(f"  {'✅' if ok else '❌'} {name}：{detail}")

    sched = schedule_d11_state(root)
    check("D11 定时开关记录", True,
          f"schedule_enabled={sched.get('schedule_enabled')}（已记入状态机，步骤十判定输入）")
    test_dir = root / "instances" / "_upgrade_test"
    test_db = data_dir(root) / "warehouse" / "_upgrade_test.duckdb"
    leftovers = []
    if test_dir.exists():
        shutil.rmtree(test_dir, ignore_errors=True)
        leftovers.append("instances/_upgrade_test")
    if test_db.exists():
        test_db.unlink()
        leftovers.append("data/warehouse/_upgrade_test.duckdb")
    for wal in test_db.parent.glob(test_db.name + ".wal"):
        wal.unlink()
    check("_upgrade_test 清理", True, ("已删除残留并告警：" + "、".join(leftovers)) if leftovers
          else "无残留（canary 已自清）✅")
    deps, deps_ok = _dependency_check(root)
    bad = [d for d in deps if not d["ok"]]
    check("依赖指纹", deps_ok,
          (f"{len(deps)} 项全满足" if deps_ok else
           "不符：" + "；".join(f"{d['name']}({d.get('note', '')})" for d in bad)),
          {"deps": deps})
    r = subprocess.run([sys.executable, str(root / "ops" / "doctor.py"), "--json"],
                       cwd=str(root), capture_output=True, timeout=600)
    try:
        doc_overall = json.loads(r.stdout.decode("utf-8", errors="replace")).get("overall", "?")
    except Exception:
        doc_overall = "解析失败"
    check("doctor 体检", r.returncode == 0, f"overall={doc_overall}")
    r = subprocess.run([sys.executable, str(root / "ops" / "launcher.py"), "--smoke"],
                       cwd=str(root), capture_output=True, timeout=300)
    smoke_out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", errors="replace")
    check("launcher --smoke", r.returncode == 0,
          ("门户自起成功" if r.returncode == 0 else
           (smoke_out.strip().splitlines()[-1] if smoke_out.strip() else f"exit {r.returncode}")))
    # 真实查询账套取值（步骤九第 3 项）：settings.json 的 instance（缺省 sales）——
    # 不用 _pick_sentinel_instance（那是哨兵基线的取值规则，含真实账套优先）
    try:
        instance = json.loads((data_dir(root) / "settings.json").read_text(encoding="utf-8")).get("instance", "sales")
    except Exception:
        instance = "sales"
    baseline_rec0 = (prog.get("backup") or {}).get("sentinel_baseline") or {}
    baseline0 = baseline_rec0.get("reports", {}) if isinstance(baseline_rec0, dict) else {}
    report = None
    dash = root / "instances" / instance / "dashboard.yml"
    if dash.is_file():
        try:
            import yaml  # lazy：smoke 为 venv 域
            reports = yaml.safe_load(dash.read_text(encoding="utf-8")).get("reports", [])
            report = reports[0].get("key") if reports else None  # 报表主键字段是 key（演练缺陷4：id 恒 None）
        except Exception:
            report = None
    if report is None:  # dashboard 解析不出时退到哨兵清单首个（同账套优先）
        for rep, base in sorted(baseline0.items()):
            if base.get("status") == "ok":
                report = rep
                break
    if report:
        rc, out, err = _run_query(root, instance, report)
        rows = _parse_report_rows(out) if rc == 0 else None
        check("真实查询", rc == 0 and isinstance(rows, list) and len(rows) > 0,
              f"{instance}/{report} → {'非空结果 ✅' if rows else '空或失败'}"
              + ("" if rc == 0 else f"（{err.strip()[-120:]}）"))
    else:
        check("真实查询", False, f"{instance} 的 dashboard.yml 无注册报表可查")
    baseline_rec = (prog.get("backup") or {}).get("sentinel_baseline") or {}
    baseline = baseline_rec.get("reports", {}) if isinstance(baseline_rec, dict) else {}
    sentinel_bad = []
    for rep, base in sorted(baseline.items()):
        if base.get("status") != "ok":
            continue
        rc, out, err = _run_query(root, base.get("instance", instance), rep)
        current = _parse_report_rows(out) if rc == 0 else None
        cmp = _compare_report(base.get("rows"), current)
        if not cmp["consistent"]:
            sentinel_bad.append({"report": rep, "diffs": cmp["diffs"][:5]})
    check("哨兵比对(真库只读)", not sentinel_bad,
          "全部一致 ✅" if not sentinel_bad
          else f"不一致：{[b['report'] for b in sentinel_bad]}（口径变更以 UPGRADE.md 为唯一豁免；需人工确认）",
          {"mismatches": sentinel_bad})

    failed = [c for c in checks if c["status"] == "fail"]
    prog["steps"] = (prog.get("steps") or []) + ["smoke"]
    prog["smoke"] = {"at": now_iso(), "schedule_enabled": sched.get("schedule_enabled"),
                     "checks": [{k: c[k] for k in ("check", "status", "detail")} for c in checks]}
    state["in_progress"] = prog
    _save_json_file(state_file, state)
    lines.append(f"[smoke] 结论：{'通过（exit 0）' if not failed else '未过 ' + str(len(failed)) + ' 项，exit 1——进步骤十 rollback'}")
    return (0 if not failed else 1), ("ok" if not failed else "fail"), lines, {"checks": checks}


# ---------------------------------------------------------------- 子命令：rollback（3.3 步骤十，纯标准库，py -3）

def _find_staging(root: Path) -> Path | None:
    ups = root.parent / "upgrade"
    stagings = sorted(ups.glob("staging-v*")) if ups.is_dir() else []
    return stagings[0] if stagings else None


def cmd_rollback(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """回滚（py -3 执行，纯标准库；新旧两侧代码都能执行它）。情形判定主证据=快照指纹
    实测（金库 size+mtime 对 backup_manifest，任一偏离即情形 B），state 步骤记录仅
    辅助；schedule_enabled=true 一律情形 B（D11 补跑无法事后排除）。情形 B 先恢复
    快照（temp+SHA256 核对+replace，介质损坏绝不覆盖现场）再执行情形 A 换回。
    Gitea 铁律：finalize 已跑必已写库→必然情形 B。"""
    root: Path = ctx.root
    channel = "G" if (root / ".git").exists() else "Z"
    state_file = _state_file_for(root)
    state = _load_json_file(state_file)
    if not isinstance(state, dict):
        raise UpgradeError(f"状态机不可读：{state_file}——人工按手册 R-14 处置")
    prog = state.get("in_progress")
    if not prog:
        raise UpgradeError("无 in_progress——没有开着窗口的升级可回滚")
    lines: list[str] = [f"[rollback] 通道 {channel}｜from={prog.get('from')} → target={prog.get('target')}"]

    backup_rec = prog.get("backup") or {}
    snap_dir = backup_rec.get("snapshot_dir")
    if not snap_dir:
        lines.append("[rollback] 状态机无 backup 记录（版本移动前的中止）——走情形 0（无数据可恢复）")
        mig_state = state
        if (state.get("migrate") or {}).get("intent"):
            staging = _find_staging(root)
            if staging:
                lines.append("[rollback] 已搬迁项逆向搬回（等价 migrate --revert）")
                rc0 = _migrate_revert(root, staging, state, lines)[0]  # lines 就地追加
                if rc0 != 0:
                    return 1, "fail", lines, {"case": "0", "note": "逆向搬回失败——人工按 R-14"}
        return _rollback_finish(root, state, state_file, lines, case="0",
                                note="版本未移动/无快照，仅复位状态机")
    snap = Path(snap_dir)
    # ---- B1（红队复现）：通道 Z 且 switch 未发生（migrate 后中止）——data/ 在 staging
    #      侧，必须先逆向搬回旧根再做任何判定/恢复。否则：①情形判定按 root 侧实测
    #      会把金库误记「缺失」误判情形 B；②恢复经 data_dir(root) 把 data/ 重造进旧根；
    #      ③随后 _migrate_revert 撞「源目标并存」失败，两侧 data/ 并存需人工处置。
    #      先回搬另治愈：backup 记录的 snapshot_dir 是 migrate 前的绝对路径，data/
    #      回到旧根后该记录路径重新有效。----
    switch_rec = prog.get("switch") or {}
    if channel == "Z" and not switch_rec:
        done_items = [it for it in ((state.get("migrate") or {}).get("intent") or [])
                      if it.get("status") == "done"]
        if done_items:
            staging = _find_staging(root)
            if staging is None:
                raise UpgradeError("已搬迁（migrate done）但找不到 staging——人工按 R-14 处置，"
                                   "不得在双侧位置不明时盲目恢复")
            lines.append(f"[rollback] migrate 后、switch 前的中止：先逆向搬回 {len(done_items)} 项"
                         f"（data/ 回旧根后判定与恢复才落在正确一侧）")
            rc0 = _migrate_revert(root, staging, state, lines)[0]  # lines 就地追加
            if rc0 != 0:
                return 1, "fail", lines, {"case": "0", "note": "逆向搬回失败——人工按 R-14"}
        else:
            lines.append("[rollback] 版本未移动且无已搬项——data/ 本在旧根，直接判定")

    bmanifest = _load_json_file(snap / "backup_manifest.json")
    if not isinstance(bmanifest, dict):
        raise UpgradeError(f"快照 manifest 不可读：{snap / 'backup_manifest.json'}——人工按 R-14 手工拷回")
    bmanifest["_snapshot_dir"] = str(snap)

    # ---- 情形判定（主证据：金库 size+mtime 实测；history/state 仅辅助）----
    drift = []
    for f in bmanifest.get("files", []):
        if not f["path"].startswith("data/warehouse/"):
            continue
        live = data_dir(root) / f["path"][len("data/"):]
        if not live.exists():
            drift.append(f"{f['path']}（缺失）")
        elif live.stat().st_size != f.get("size") or abs(live.stat().st_mtime - f.get("mtime", 0)) > 0.001:
            drift.append(f"{f['path']}（size/mtime 偏离）")
    sched_enabled = (prog.get("smoke") or {}).get("schedule_enabled")
    if sched_enabled is None:
        try:
            sched_enabled = bool(json.loads(
                (data_dir(root) / "settings.json").read_text(encoding="utf-8")).get("schedule_enabled", False))
        except Exception:
            sched_enabled = True  # 读不出按保守（视同 B）
    finalize_ran = "finalize" in (prog.get("steps") or [])
    case_b = bool(drift) or sched_enabled is True or finalize_ran
    lines.append(f"[rollback] 情形判定：金库指纹偏离 {len(drift)} 项｜schedule_enabled={sched_enabled}"
                 f"｜finalize 已跑={finalize_ran} → 情形 {'B（先恢复快照再换回）' if case_b else 'A（直接换回）'}")
    for d in drift[:5]:
        lines.append(f"    偏离：{d}")

    prev = Path(switch_rec["prev_dir"]) if switch_rec.get("prev_dir") else None
    if channel == "Z" and switch_rec and not (prev and prev.is_dir()):
        raise UpgradeError(f"prev 槽位缺失（{prev}）——人工按手册 R-14 手工拷回（恢复方式与备份数据.bat 声明一致）")

    # ---- 情形 B：先恢复快照（通道 G 的 reset 先行、快照字节后落，防 reset --hard
    #      覆盖已恢复的受管文件；通道 Z 恢复进新根，随后整体带回 prev）----
    if case_b and channel == "G":
        head0 = backup_rec.get("git_head")
        if not head0:
            raise UpgradeError("通道 G 回滚缺升级前 HEAD（backup 未记录）——人工 git reflog 处置")
        r = _git(root, "reset", "--hard", head0)
        if r.returncode != 0:
            raise UpgradeError("git reset --hard 失败：" + r.stderr.decode(errors="replace").strip()[:300])
        lines.append(f"[rollback] 通道 G：git reset --hard {head0[:12]} ✅（代码先回旧版）")
        lines.append("[rollback] 情形 B：恢复快照字节（本地态覆盖受管文件，保口径本地修改）")
        if not _restore_snapshot(root, bmanifest, lines):
            return 1, "fail", lines, {"case": "B", "restored": False, "drift": drift}
        lines.append("[rollback] 快照恢复核对全过（Gitea 铁律：旧代码不读被新结构改写过的库）")
    elif case_b:
        lines.append("[rollback] 情形 B：恢复快照字节（落当前新根，随后随搬迁整体带回 prev）")
        if not _restore_snapshot(root, bmanifest, lines):
            return 1, "fail", lines, {"case": "B", "restored": False, "drift": drift}
        lines.append("[rollback] 快照恢复核对全过（Gitea 铁律：旧代码不读被新结构改写过的库）")

    # ---- 情形 A 动作 ----
    if channel == "G":
        if not case_b:
            head0 = backup_rec.get("git_head")
            if not head0:
                raise UpgradeError("通道 G 回滚缺升级前 HEAD（backup 未记录）——人工 git reflog 处置")
            r = _git(root, "reset", "--hard", head0)
            if r.returncode != 0:
                raise UpgradeError("git reset --hard 失败：" + r.stderr.decode(errors="replace").strip()[:300])
            lines.append(f"[rollback] 通道 G：git reset --hard {head0[:12]} ✅")
    else:
        if not switch_rec:
            # B1：逆向搬回已在情形判定前完成（见上方），此处只收尾——
            # 版本未动过（root 仍是旧代码），恢复过的字节已在 root/data 落位
            return _rollback_finish(root, state, state_file, lines, case="0",
                                    note="版本未移动（migrate 后中止），搬迁已回退"
                                         + ("，快照字节已恢复" if case_b else ""))
        tenants = (state.get("last_plan") or {}).get("manifest", {}).get("tenants_builtin", [])
        items, _skip = _build_migrate_intent(root, tenants)
        move_fail = None
        for it in items:
            src, dst = root / it["rel"], prev / it["rel"]
            s_in, d_in = src.exists(), dst.exists()
            if s_in and not d_in:
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.rename(src, dst)
                    if it.get("bytes") is not None and _item_bytes(prev, it) != it["bytes"]:
                        move_fail = (it["rel"], "搬入 prev 后字节数不符")
                        break
                    lines.append(f"  [回搬] {it['rel']} → prev")
                except OSError as exc:
                    move_fail = (it["rel"], str(exc))
                    break
            elif not s_in and d_in:
                lines.append(f"  [已在 prev] {it['rel']}")
            elif not s_in and not d_in:
                if it.get("mandatory"):
                    move_fail = (it["rel"], "源与 prev 皆缺（必选项）")
                    break
            else:
                move_fail = (it["rel"], "产品根与 prev 并存——人工分诊")
                break
        if move_fail:
            lines.append(f"[rollback] 搬回 prev 失败：{move_fail[0]}——{move_fail[1]}；"
                         f"已搬项已在 prev，重试 rollback 幂等续跑")
            return 1, "fail", lines, {"case": "A/B", "move_fail": move_fail}
        ups = root.parent / "upgrade"
        failed_dir = ups / f"failed-{now_stamp()}"
        n = 2
        while failed_dir.exists():
            failed_dir = ups / f"failed-{now_stamp()}-{n}"
            n += 1
        try:
            os.rename(root, failed_dir)
        except OSError as exc:
            raise UpgradeError(f"rename 新根→failed 失败（持久资产已入 prev，重试 rollback 续跑）：{exc}")
        try:
            os.rename(prev, root)
        except OSError as exc:
            try:
                os.rename(failed_dir, root)
            except OSError:
                pass
            raise UpgradeError(f"rename prev→产品根 失败（{exc}）——人工：把 {prev} 改回 {root}")
        lines.append(f"[rollback] 槽位换回：新根 → {failed_dir.name}，prev → 产品根 ✅")

    # ---- 依赖复核 + 收尾 ----
    # 演练缺陷5：rollback 在 py -3（系统解释器）下跑，不传 python_exe 会以当前解释器
    # 探测 installed（系统 Python 无产品包）→ 恒判不符 → 每次回滚多跑一次 pip install。
    # 改为经产品 venv 探测（与 doctor/launcher 同一探测路径）。
    venv_py0 = root / ".venv" / "Scripts" / "python.exe"
    deps, deps_ok = (_dependency_check(root, python_exe=venv_py0)
                     if venv_py0.is_file() else (None, False))
    venv_py = root / ".venv" / "Scripts" / "python.exe"
    if not deps_ok and venv_py.is_file() and (root / "requirements.txt").is_file():
        r = subprocess.run([str(venv_py), "-m", "pip", "install", "-r", "requirements.txt"],
                           cwd=str(root), capture_output=True, timeout=1800)
        lines.append(f"[rollback] 按升级前 requirements 刷新依赖：{'完成 ✅' if r.returncode == 0 else '失败（人工处置）'}")
    elif not deps_ok:
        lines.append("[rollback] ⚠️ 依赖不符且 venv/requirements 不可用——跳过自动刷新，人工处置")
    else:
        lines.append("[rollback] 依赖与升级前 requirements 一致，无需刷新 ✅")
    return _rollback_finish(root, state, state_file, lines, case="B" if case_b else "A", note="")


def _rollback_finish(root: Path, state: dict, state_file: Path, lines: list[str],
                     case: str, note: str) -> tuple[int, str, list[str], dict]:
    """回滚收尾：VERSION 复核、重启门户、doctor 复检、清 in_progress（窗口关）。
    核心恢复已在此前完成——收尾各步逐一容错（失败记 warn/计 rc），状态机清位
    无论如何执行（窗口语义不能卡死在坏 venv 上）。"""
    rc_overall = 0
    try:
        ver = read_local_version(root)
        lines.append(f"[rollback] VERSION 复核：{ver}")
    except Exception as exc:
        lines.append(f"[rollback] ❌ VERSION 不可读：{exc}")
        rc_overall = 1
    venv_py = root / ".venv" / "Scripts" / "python.exe"
    if venv_py.is_file():
        try:
            (root / "logs").mkdir(parents=True, exist_ok=True)
            logf = open(root / "logs" / "uvicorn.log", "ab")
            subprocess.Popen([str(venv_py), "-m", "uvicorn", "app.main:app",
                              "--host", "127.0.0.1", "--port", "8620"],
                             cwd=str(root), stdout=logf, stderr=subprocess.STDOUT)
            lines.append("[rollback] 门户重启已发起（doctor 复检确认）")
        except Exception as exc:
            lines.append(f"[rollback] ⚠️ 门户重启发起失败：{exc}——人工按 R-07 启动")
            rc_overall = 1
        time.sleep(4)
        try:
            r = subprocess.run([str(venv_py), str(root / "ops" / "doctor.py"), "--json"],
                               cwd=str(root), capture_output=True, timeout=600)
            try:
                overall = json.loads(r.stdout.decode("utf-8", errors="replace")).get("overall")
            except Exception:
                overall = "?"
            lines.append(f"[rollback] doctor 复检：overall={overall}")
            if r.returncode != 0:
                rc_overall = 1
        except Exception as exc:
            lines.append(f"[rollback] ⚠️ doctor 复检执行失败：{exc}")
            rc_overall = 1
    else:
        lines.append("[rollback] ⚠️ 产品根无 .venv python——跳过门户重启与 doctor 复检"
                     "（人工按 R-07/R-01 处置）")
        rc_overall = 1
    state["in_progress"] = None
    if state.pop("migrate", None) is not None:
        # 演练缺陷2：回滚即整体退回升级前状态，搬迁意图随之作废（防二次升级沿用残留）
        lines.append("[rollback] 已清除搬迁意图（state.migrate）——回滚后无半搬语义可续")
    state["last_rollback"] = {"at": now_iso(), "case": case, "note": note}
    _save_json_file(_state_file_for(root), state)
    lines.append(f"[rollback] 完成（情形 {case}）：in_progress 已清位，窗口关闭")
    return rc_overall, ("ok" if rc_overall == 0 else "fail"), lines, {"case": case}


# ---------------------------------------------------------------- 子命令：finalize（3.3 步骤十一）

def cmd_finalize(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    """收尾记账（产品根 venv）：VERSION 复核（=目标）、前端 ?v= 复核（static mtime
    晚于 ?v= 日期串则 warn——落点 7e 的体检逻辑前置）、快照与 prev 清单提示。
    正式三步链与人类门户验收不代跑（照 AGENTS 配方/手册 R-14 执行）——回滚窗口
    保持开启直至 prune（步骤十可用边界）。"""
    root: Path = ctx.root
    state_file = state_path(root)
    state = _load_json_file(state_file) or {}
    prog = state.get("in_progress") if isinstance(state, dict) else None
    if not prog:
        raise UpgradeError("无 in_progress——没有开着窗口的升级可收尾")
    target = prog.get("target")
    lines: list[str] = []

    ver = read_local_version(root)
    if ver != target:
        raise UpgradeError(f"VERSION 复核未过：当前 {ver} ≠ 目标 {target}——版本移动异常，走 rollback")
    lines.append(f"[finalize] VERSION 复核 ✅：{ver} == {target}")

    idx = root / "app" / "static" / "index.html"
    v_warns: list[str] = []
    newest = None
    if idx.is_file():
        stamps = re.findall(r"\?v=(\d{8})", idx.read_text(encoding="utf-8"))
        newest = max(stamps) if stamps else None
        if newest:
            import datetime as _dt
            cutoff = _dt.datetime.strptime(newest, "%Y%m%d").timestamp()
            for f in (root / "app" / "static").rglob("*"):
                if f.is_file() and f.stat().st_mtime > cutoff:
                    v_warns.append(f.relative_to(root).as_posix())
        if v_warns:
            lines.append(f"[finalize] ⚠️ ?v= 复核：{len(v_warns)} 个 static 文件 mtime 晚于 ?v={newest}"
                         f"——浏览器缓存串漏风险（红线；示例：{v_warns[:3]}）")
        elif newest:
            lines.append(f"[finalize] ?v= 复核 ✅：static 无晚于 ?v={newest} 的文件")
        else:
            lines.append("[finalize] ⚠️ index.html 内无 ?v= 日期串——无法复核")
    else:
        lines.append("[finalize] ⚠️ app/static/index.html 缺失——?v= 复核跳过（布局异常？）")

    broot = data_dir(root) / "backup"
    snaps = sorted((p for p in broot.iterdir() if p.is_dir() and p.name.startswith("pre-upgrade-")),
                   key=lambda p: p.name, reverse=True) if broot.is_dir() else []
    lines.append(f"[finalize] 升级快照共 {len(snaps)} 份（建议保留最近 3 份，更早的人确认后手删——"
                 f"prune 与本工具永不自动删快照）：")
    for p in snaps[:3]:
        lines.append(f"    保留建议内：{p.name}")
    for p in snaps[3:]:
        lines.append(f"    更早（待人工手删）：{p.name}")
    ups = root.parent / "upgrade"
    prevs = sorted(p.name for p in ups.glob("prev-v*")) if ups.is_dir() else []
    if prevs:
        lines.append(f"[finalize] prev 槽位 {len(prevs)} 代（{', '.join(prevs)}）——收敛走 prune（保留最近两代）")
    lines.append("[finalize] 正式三步链与人类门户验收不代跑：按 AGENTS 配方逐账套跑 ingest+compile+build，"
                 "人工在门户确认报表口径（D6：全量重建 marts）")
    lines.append("[finalize] 回滚窗口保持开启直至 prune（验收不过随时 rollback；finalize 后必走情形 B）")

    prog["steps"] = (prog.get("steps") or []) + ["finalize"]
    prog["finalize"] = {"at": now_iso(), "version": ver, "v_check_warns": v_warns,
                        "chain_and_acceptance": "manual（按 R-14，不代跑）",
                        "snapshots": [p.name for p in snaps]}
    state["in_progress"] = prog
    _save_json_file(state_file, state)
    return 0, "ok", lines, {"version": ver, "v_check_warns": v_warns,
                            "snapshots": [p.name for p in snaps]}


# ---------------------------------------------------------------- 子命令：status

def cmd_status(ctx: argparse.Namespace) -> tuple[int, str, list[str], dict]:
    root: Path = ctx.root
    layout = detect_channel_layout(root)
    try:
        local = read_local_version(root)
        parse_semver(local)
        ver_note = f"VERSION={local}"
    except Exception as exc:
        local, ver_note = None, f"VERSION 不可读：{exc}"
    state = read_state(root)
    up_dir = data_dir(root) / "upgrade"
    logs_dir = up_dir / "logs"
    logs = sorted(p.name for p in logs_dir.glob("*.json"))[-10:] if logs_dir.is_dir() else []
    reports = sorted(p.name for p in up_dir.glob("plan_*.json")) if up_dir.is_dir() else []
    lines = [
        f"[status] 产品根：{root}",
        f"[status] 通道 {layout['channel']} / 模式 {layout['mode']}｜{ver_note}",
        f"[status] 状态机：{'无 state.json（未执行过协议步骤）' if state is None else json.dumps({'in_progress': state.get('in_progress'), 'updated_at': state.get('updated_at')}, ensure_ascii=False)}",
        f"[status] 运行日志 {len(logs)} 份（最近：{logs[-1] if logs else '无'}）｜分诊报告 {len(reports)} 份",
    ]
    data = {"channel": layout["channel"], "mode": layout["mode"],
            "local_version": local, "layout_detail": layout["detail"],
            "state": state, "recent_logs": logs, "plan_reports": reports}
    return 0, "ok", lines, data


# ---------------------------------------------------------------- 占位子命令

def cmd_placeholder(ctx: argparse.Namespace, step: str) -> tuple[int, str, list[str], dict]:
    layout = detect_channel_layout(ctx.root)
    note = STEP_NOT_IMPLEMENTED_NOTE[step]
    lines = [f"[{step}] 骨架占位：{note}",
             f"[{step}] 探测：通道 {layout['channel']} / 模式 {layout['mode']}（真实步骤实现后按通道分流）",
             f"[{step}] exit 3（not_implemented）"]
    return 3, "not_implemented", lines, {"note": note, "channel": layout["channel"],
                                         "mode": layout["mode"]}


# ---------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ops/upgrade.py",
        description="明账 ClearLedger 无损升级协议引擎（骨架版）——规格见 "
                    "internal/docs/无损升级架构方案-20260930.md。"
                    "用法：python ops/upgrade.py [--root <产品根>] [--json] <子命令> [参数]"
                    "（--root/--json 须在子命令之前，沿 6.4 命令形态）")
    parser.add_argument("--root", default=str(ROOT),
                        help="产品根（默认本脚本所在仓库根；首升场景指向旧根，6.4）")
    parser.add_argument("--json", action="store_true",
                        help="末行追加完整机器 JSON")
    sub = parser.add_subparsers(dest="step", required=True, metavar="<子命令>")

    def add(name: str, help_text: str, *args: tuple) -> None:
        sp = sub.add_parser(name, help=help_text)
        for flag, kw in args:
            sp.add_argument(flag, **kw)

    add("plan", "步骤一（只读）：拉 manifest、比对版本、产出分诊报告",
        ("--target", {"type": validate_semver, "help": "目标 tag（缺省自动查 Releases latest）"}),
        ("--manifest", {"help": "直接指定 manifest：本地路径或 http(s) URL（本地路径用于演练与测试）"}))
    add("preflight", "步骤二（只读）：通道/磁盘/版本方向/端口/D11 等环境闸门",
        ("--target", {"type": validate_semver, "help": "目标 tag"}),
        ("--manifest", {"help": "直接指定 manifest：本地路径或 http(s) URL"}))
    add("stage", "步骤三（通道 Z 专属）：下载/解包/静态检查/builtin diff——占位（首升按 6.4 引导命令手工解包）",
        ("--target", {"type": validate_semver, "required": True, "help": "目标 tag"}))
    add("stop", "步骤四：停机（杀 8620、金库写锁复查、开窗置位）")
    add("backup", "步骤五（硬闸门 R1）：ops/backup.py 快照+哨兵基线+通道 G 记 HEAD")
    add("migrate", "步骤六 6A（通道 Z，py -3）：持久资产搬迁（意图化、幂等、--revert 逆向）",
        ("--revert", {"action": "store_true", "help": "按 state.json 逆向 rename 回旧根（整体退回）"}))
    add("switch", "步骤六 6A（通道 Z，py -3）：槽位换名（旧根→prev、staging→产品根）")
    add("sync", "步骤六 6B（通道 G）：fetch+生成物还原+两段 merge+祖先校验+登记簿对账指引")
    add("canary", "步骤八（mart_schema_changed=true 时）：_upgrade_test 金丝雀+哨兵比对",
        ("--instance", {"type": validate_instance, "required": True, "help": "金丝雀账套（3.3 步骤八取值规则）"}))
    add("smoke", "步骤九：门户冒烟（D11 记录+_upgrade_test 复验+依赖指纹+doctor+launcher 自测+真实查询+哨兵）")
    add("rollback", "步骤十（py -3）：情形判定（快照指纹+schedule_enabled）与恢复，关窗清位")
    add("finalize", "步骤十一：记账+VERSION/?v= 复核+快照与 prev 清单提示（三步链与验收按 R-14 手动）")
    add("prune", "步骤十一（通道 Z）：prev 收敛到最近两代+快照只列不删+关窗清位")
    add("status", "查看：通道/布局/版本/状态机/日志——只读")
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    step: str = args.step
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[{step}] 失败：--root 指向的目录不存在：{root}", file=sys.stderr)
        return 1
    args.root = root  # 子命令统一拿 Path（防 str 拼路径）

    try:
        if step == "plan":
            exit_code, status, lines, data = cmd_plan(args)
        elif step == "preflight":
            exit_code, status, lines, data = cmd_preflight(args)
        elif step == "status":
            exit_code, status, lines, data = cmd_status(args)
        elif step == "stop":
            exit_code, status, lines, data = cmd_stop(args)
        elif step == "backup":
            exit_code, status, lines, data = cmd_backup(args)
        elif step == "migrate":
            exit_code, status, lines, data = cmd_migrate(args)
        elif step == "switch":
            exit_code, status, lines, data = cmd_switch(args)
        elif step == "prune":
            exit_code, status, lines, data = cmd_prune(args)
        elif step == "sync":
            exit_code, status, lines, data = cmd_sync(args)
        elif step == "canary":
            exit_code, status, lines, data = cmd_canary(args)
        elif step == "smoke":
            exit_code, status, lines, data = cmd_smoke(args)
        elif step == "rollback":
            exit_code, status, lines, data = cmd_rollback(args)
        elif step == "finalize":
            exit_code, status, lines, data = cmd_finalize(args)
        else:
            exit_code, status, lines, data = cmd_placeholder(args, step)
    except UpgradeError as exc:
        exit_code, status = 1, "fail"
        lines = list(getattr(exc, "lines", None) or []) + [f"[{step}] 失败：{exc}"]
        data = {"error": str(exc)}
    except Exception as exc:  # 未预期异常也收敛成 JSON（agent 消费退出码与 JSON）
        exit_code, status, lines, data = 1, "fail", \
            [f"[{step}] 未预期异常：{exc!r}"], {"error": repr(exc)}

    for line in lines:
        print(line)
    payload = {"step": step, "status": status, "exit_code": exit_code,
               "root": str(root), "generated_at": now_iso(), "data": data}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    try:
        archive_log(root, step, payload, sys.argv[1:])
        if step in ("plan", "preflight"):
            update_state_history(root, step, exit_code, status,
                                 lines[-1] if lines else "",
                                 {"channel": data.get("channel"),
                                  "mode": data.get("mode"),
                                  "local_version": data.get("local_version")
                                  or data.get("version_check", {}).get("local")})
    except Exception as exc:
        print(f"[{step}] 警告：运行日志/状态机写盘失败（{exc}）——不影响本步结论，"
              f"但 data/upgrade/ 需人工检查", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
