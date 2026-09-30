# -*- coding: utf-8 -*-
"""明账 ClearLedger — 全局路径与配置常量（v0.3 多账套版）"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 运行时（各账套库文件与历史按实例分置：data/warehouse/<inst>.duckdb、data/runs/history_<inst>.json）
RUNS_DIR = ROOT / "data" / "runs"
LOG_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DBT_EXE = ROOT / ".venv" / "Scripts" / "dbt.exe"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

# 门户
HOST = "127.0.0.1"
PORT = 8620

# 跑批调度默认值（可在门户"跑批设置"里开关与调整，持久化到 data/settings.json）
# 默认完全手动触发——定时是可选功能，不是默认行为
SCHEDULE_ENABLED_DEFAULT = False
SCHEDULE_HOUR = 6
SCHEDULE_MINUTE = 30

APP_NAME = "明账 ClearLedger"

# 版本单一出处：仓库根 VERSION（一行纯文本，语义化 vX.Y.Z）。
# 依据 internal/docs/无损升级架构方案-20260930.md 4 节落点 2 与 6.1 的 tag 语义。
# 读不到时回退 _APP_VERSION_FALLBACK 并向 stderr 显式告警，绝不静默失真——
# 此处曾写死 "v0.3" 而项目实际已到 v0.6，失真两个版本的教训。
_VERSION_SEMVER_RE = re.compile(r"v\d+\.\d+\.\d+")
_APP_VERSION_FALLBACK = "v0.6.0"


def _load_app_version() -> str:
    version_file = ROOT / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        print(f"[config] 警告：读不到 {version_file}（{exc}），APP_VERSION 回退 "
              f"{_APP_VERSION_FALLBACK}——版本显示已失真，请恢复仓库根的 VERSION 文件",
              file=sys.stderr)
        return _APP_VERSION_FALLBACK
    if not value:
        print(f"[config] 警告：{version_file} 内容为空，APP_VERSION 回退 {_APP_VERSION_FALLBACK}",
              file=sys.stderr)
        return _APP_VERSION_FALLBACK
    if not _VERSION_SEMVER_RE.fullmatch(value):
        print(f"[config] 警告：{version_file} 值 {value!r} 不符合 vX.Y.Z 语义"
              f"（升级协议 plan 比对依赖它），请修正", file=sys.stderr)
    return value


APP_VERSION = _load_app_version()
