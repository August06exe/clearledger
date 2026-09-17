# -*- coding: utf-8 -*-
"""明账 ClearLedger — 数据摄取（inbox → DuckDB raw 层）

读取 ingest/sources.yml 声明的数据源，把 data/inbox/ 里的 Excel/CSV
清洗为规整的英文列名宽表，落入 DuckDB 的 raw schema（快照式全量覆盖）。

约定：
  - 任一数据源失败 → 退出码非 0 → 本轮跑批亮红灯
  - 每次摄取在 raw.load_log 留痕（源文件、行数、时间、状态）

用法：.venv/Scripts/python ingest/ingest.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "ingest" / "sources.yml"
WAREHOUSE = ROOT / "data" / "warehouse" / "warehouse.duckdb"
LOG_DIR = ROOT / "logs"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_file(inbox: Path, patterns: list[str]) -> Path | None:
    """按声明顺序找第一个存在的文件；支持通配符。"""
    for pat in patterns:
        hits = sorted(inbox.glob(pat))
        if hits:
            return hits[0]
    return None


def connect_with_retry(path: Path, attempts: int = 20, delay: float = 0.5) -> duckdb.DuckDBPyConnection:
    """门户可能正在查询（读锁），短重试避免互撞误报红灯"""
    last: Exception | None = None
    for _ in range(attempts):
        try:
            return duckdb.connect(str(path))
        except duckdb.IOException as e:
            last = e
            time.sleep(delay)
    raise RuntimeError(f"数据仓库被占用（门户正在查询？）：{last}")


def read_file(path: Path, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        try:
            return pd.read_csv(path, encoding="utf-8-sig", dtype=str)
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="gbk", dtype=str)  # 国内业务导出常见 GBK
    if fmt == "xlsx":
        return pd.read_excel(path, engine="openpyxl", dtype=str)
    raise ValueError(f"不支持的格式: {fmt}")


def ingest_source(con: duckdb.DuckDBPyConnection, inbox: Path, src: dict) -> dict:
    name = src["name"]
    path = resolve_file(inbox, src.get("files", []))
    if path is None:
        raise FileNotFoundError(f"数据源 [{src.get('title', name)}] 找不到文件: {src.get('files')}（投放区 {inbox}）")

    df = read_file(path, src["format"])
    df.columns = [str(c).strip() for c in df.columns]

    if df.empty:
        raise ValueError(f"数据源 [{src.get('title', name)}] 文件 {path.name} 是空表（0 行）。"
                         f"请确认导出是否完整；若确为空期数据，请咨询 AI 助手如何处理。")

    col_map = src.get("column_map", {})
    missing = [c for c in col_map if c not in df.columns]
    if missing:
        raise ValueError(f"数据源 [{name}] 文件 {path.name} 缺少声明的列: {missing}（表头变了？）")
    df = df.rename(columns=col_map)
    df = df[[c for c in df.columns if not str(c).startswith("Unnamed")]]

    # 字符串去首尾空格（脏数据第一道防线）
    for c in df.columns:
        if df[c].dtype == object or str(df[c].dtype) == "string":
            df[c] = df[c].astype("string").str.strip()
            df[c] = df[c].replace({"": None})

    for c in src.get("date_columns", []) or []:
        df[c] = pd.to_datetime(df[c], errors="raise")

    for c in src.get("numeric_columns", []) or []:
        before_null = df[c].isna().sum()
        df[c] = pd.to_numeric(df[c], errors="coerce")
        coerced = int(df[c].isna().sum() - before_null)
        if coerced:
            print(f"  [warn] {name}.{c}: {coerced} 行无法解析为数值，已置空")

    # 溯源列：这行数据来自哪个文件、何时入库
    df["_source_file"] = path.name
    df["_loaded_at"] = datetime.now().isoformat(timespec="seconds")

    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.register("df_inbox_view", df)
    con.execute(f'CREATE OR REPLACE TABLE raw."{name}" AS SELECT * FROM df_inbox_view')
    con.unregister("df_inbox_view")

    con.execute(
        """CREATE TABLE IF NOT EXISTS raw.load_log (
               loaded_at TIMESTAMP, source_name VARCHAR, source_file VARCHAR,
               rows BIGINT, status VARCHAR, message VARCHAR)"""
    )
    con.execute(
        "INSERT INTO raw.load_log VALUES (?, ?, ?, ?, 'ok', ?)",
        [df["_loaded_at"].iloc[0], name, path.name, len(df), "全量覆盖"],
    )
    return {"source": name, "file": path.name, "rows": int(len(df)), "status": "ok"}


def main() -> int:
    cfg = load_config()
    # inbox_dir 相对于本配置文件（ingest/）解析
    inbox = (CONFIG_PATH.parent / cfg.get("inbox_dir", "../data/inbox")).resolve()
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    results, errors = [], []
    con = connect_with_retry(WAREHOUSE)
    try:
        for src in cfg.get("sources", []):
            try:
                r = ingest_source(con, inbox, src)
                results.append(r)
                print(f"  [ok]   {r['source']:22s} ← {r['file']}  {r['rows']:,} 行")
            except Exception as e:  # 单源失败不阻断其他源，但整体亮红灯
                errors.append({"source": src.get("name"), "error": str(e)})
                results.append({"source": src.get("name"), "status": "error", "error": str(e)})
                print(f"  [FAIL] {src.get('name')}: {e}", file=sys.stderr)
    finally:
        con.close()

    report = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "inbox": str(inbox),
        "results": results,
        "ok": not errors,
    }
    (LOG_DIR / "ingest_last.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"摄取完成：{sum(1 for r in results if r['status'] == 'ok')}/{len(results)} 个数据源成功")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
