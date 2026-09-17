# -*- coding: utf-8 -*-
"""DuckDB 连接助手

跑批（ingest / dbt）期间仓库文件带写锁，此时只读连接会抛 IOException；
这里统一做带重试的只读连接，超过等待时间则抛错，由 API 层转 503。
"""
from __future__ import annotations

import time

import duckdb

from app import config

RETRIES = 20          # 20 × 0.5s = 最多等 10s
DELAY = 0.5


def connect(readonly: bool = True) -> duckdb.DuckDBPyConnection:
    if not config.WAREHOUSE.exists():
        raise FileNotFoundError(f"仓库文件不存在：{config.WAREHOUSE}（先跑一次数据管道）")
    last: Exception | None = None
    for _ in range(RETRIES):
        try:
            return duckdb.connect(str(config.WAREHOUSE), read_only=readonly)
        except duckdb.IOException as e:  # 写锁占用
            last = e
            time.sleep(DELAY)
    raise RuntimeError(f"数据仓库被占用（可能正在跑批），请稍后刷新：{last}")


def query_df(sql: str, params: list | None = None):
    con = connect()
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


def query_dicts(sql: str, params: list | None = None) -> list[dict]:
    df = query_df(sql, params)
    return df_to_dicts(df)


def df_to_dicts(df) -> list[dict]:
    """DataFrame → JSON 安全的记录列表（日期转 ISO 字符串，NaN 转 None，Decimal 转 float）"""
    from decimal import Decimal

    if df is None or len(df) == 0:
        return []
    df = df.copy()
    for c in df.columns:
        if str(df[c].dtype).startswith("datetime"):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
        else:
            df[c] = df[c].map(lambda x: float(x) if isinstance(x, Decimal) else x)
        df[c] = df[c].where(df[c].notna(), None)
    return df.to_dict("records")
