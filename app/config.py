# -*- coding: utf-8 -*-
"""明账 ClearLedger — 全局路径与配置常量"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 存储与管道
WAREHOUSE = ROOT / "data" / "warehouse" / "warehouse.duckdb"
DBT_DIR = ROOT / "pipeline"
DBT_EXE = ROOT / ".venv" / "Scripts" / "dbt.exe"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
INGEST_PY = ROOT / "ingest" / "ingest.py"
MANIFEST = DBT_DIR / "target" / "manifest.json"
RUN_RESULTS = DBT_DIR / "target" / "run_results.json"

# 运行时
RUNS_DIR = ROOT / "data" / "runs"
LOG_DIR = ROOT / "logs"
DATA_DIR = ROOT / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# 门户
HOST = "127.0.0.1"
PORT = 8620

# 跑批调度默认值（可在门户"跑批设置"里开关与调整，持久化到 data/settings.json）
# 默认完全手动触发——定时是可选功能，不是默认行为
SCHEDULE_ENABLED_DEFAULT = False
SCHEDULE_HOUR = 6
SCHEDULE_MINUTE = 30

APP_NAME = "明账 ClearLedger"
APP_VERSION = "v0.2-nightly"
