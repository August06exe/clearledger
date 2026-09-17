# -*- coding: utf-8 -*-
"""报表注册表

每个管理报表 = 标题/说明 + 参数定义 + 列标签（中文表头 & Excel 导出表头）+ 查询函数。
口径铁律：报表只查 marts 层，不允许在报表层重算口径。
"""
from __future__ import annotations

from app.services import duck


def _as_int(v, default: int, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _in_whitelist(v, options: list[str], default=None):
    return v if v in options else default


def _distinct(column: str, table: str) -> list[str]:
    rows = duck.query_dicts(
        f"select distinct {column} as v from {table} order by 1"  # 列名/表名来自代码内注册表，非用户输入
    )
    return [r["v"] for r in rows if r["v"] is not None]


def _run_monthly_kpi(p: dict):
    n = _as_int(p.get("months"), 12, 1, 36)
    sql = """
    select * from (
        select * from marts.mart_kpi_monthly
        where month < date_trunc('month', current_date)
        order by month desc limit ?
    ) order by month
    """
    return sql, [n]


def _run_region_month(p: dict):
    n = _as_int(p.get("months"), 12, 1, 36)
    regions = _distinct("region_code", "marts.mart_region_month")
    region = _in_whitelist(p.get("region"), regions)
    sql = """
    with m as (
        select distinct month from marts.mart_region_month
        where month < date_trunc('month', current_date)
        order by month desc limit ?
    )
    select r.* from marts.mart_region_month r join m on r.month = m.month
    """
    params: list = [n]
    if region:
        sql += " where r.region_code = ?"
        params.append(region)
    sql += " order by r.month desc, r.region_code"
    return sql, params


def _run_customer_summary(p: dict):
    regions = _distinct("region_code", "marts.mart_customer_summary")
    levels = _distinct("customer_level", "marts.mart_customer_summary")
    region = _in_whitelist(p.get("region"), regions)
    level = _in_whitelist(p.get("level"), levels)
    limit = _as_int(p.get("limit"), 100, 1, 1000)
    sql = "select * from marts.mart_customer_summary where 1=1"
    params: list = []
    if region:
        sql += " and region_code = ?"
        params.append(region)
    if level:
        sql += " and customer_level = ?"
        params.append(level)
    sql += " order by ltm_revenue desc limit ?"
    params.append(limit)
    return sql, params


def _run_product_month(p: dict):
    n = _as_int(p.get("months"), 6, 1, 36)
    cats = _distinct("category", "marts.mart_product_month")
    category = _in_whitelist(p.get("category"), cats)
    sql = """
    with m as (
        select distinct month from marts.mart_product_month
        where month < date_trunc('month', current_date)
        order by month desc limit ?
    )
    select r.* from marts.mart_product_month r join m on r.month = m.month
    """
    params: list = [n]
    if category:
        sql += " where r.category = ?"
        params.append(category)
    sql += " order by r.month desc, r.revenue desc"
    return sql, params


def _run_expense_dept(p: dict):
    n = _as_int(p.get("months"), 12, 1, 36)
    sql = """
    with m as (
        select distinct month from marts.mart_expense_dept_month
        where month < date_trunc('month', current_date)
        order by month desc limit ?
    )
    select r.* from marts.mart_expense_dept_month r join m on r.month = m.month
    order by r.month desc, r.dept_code, r.category
    """
    return sql, [n]


REPORTS: dict[str, dict] = {
    "monthly_kpi": {
        "title": "经营月报（公司级）",
        "description": "收入 / 成本 / 毛利 / 费用 / 净利月度走势。口径出处：mart_kpi_monthly（仅含完整月）。",
        "params": [{"name": "months", "label": "最近完整月数", "type": "number", "default": 12}],
        "columns": [
            ("month", "月份"), ("revenue", "收入"), ("cost_amount", "成本"),
            ("gross_profit", "毛利"), ("expense", "费用"), ("net_profit", "净利"),
            ("gross_margin", "毛利率"), ("net_margin", "净利率"),
            ("revenue_mom", "收入环比"), ("gross_profit_mom", "毛利环比"),
        ],
        "run": _run_monthly_kpi,
    },
    "region_month": {
        "title": "区域经营月报",
        "description": "五大区域月度收入 / 毛利 / 分摊费用 / 净利与收入环比。口径出处：mart_region_month。",
        "params": [
            {"name": "months", "label": "最近完整月数", "type": "number", "default": 12},
            {"name": "region", "label": "区域", "type": "select", "options_from": "region", "default": ""},
        ],
        "columns": [
            ("month", "月份"), ("region_name", "区域"), ("revenue", "收入"),
            ("gross_profit", "毛利"), ("gross_margin", "毛利率"),
            ("allocated_expense", "分摊费用"), ("net_profit", "净利"), ("revenue_mom", "收入环比"),
        ],
        "run": _run_region_month,
    },
    "customer_summary": {
        "title": "客户经营汇总（LTM）",
        "description": "滚动 12 个月客户收入 / 毛利 / 订单数，附行业 / 等级 / 区域标签。口径出处：mart_customer_summary。",
        "params": [
            {"name": "region", "label": "区域", "type": "select", "options_from": "region", "default": ""},
            {"name": "level", "label": "客户等级", "type": "select", "options_from": "level", "default": ""},
            {"name": "limit", "label": "前 N 名", "type": "number", "default": 100},
        ],
        "columns": [
            ("customer_id", "客户编号"), ("customer_name", "客户名称"), ("industry", "行业"),
            ("customer_level", "客户等级"), ("region_name", "区域"), ("status", "状态"),
            ("order_cnt", "订单数"), ("ltm_revenue", "LTM收入"), ("ltm_gross_profit", "LTM毛利"),
            ("gross_margin", "毛利率"), ("last_order_date", "最近下单"),
        ],
        "run": _run_customer_summary,
    },
    "product_month": {
        "title": "商品月度销售",
        "description": "月 × 品类 × 商品的销量 / 收入 / 毛利。口径出处：mart_product_month。",
        "params": [
            {"name": "months", "label": "最近完整月数", "type": "number", "default": 6},
            {"name": "category", "label": "品类", "type": "select", "options_from": "category", "default": ""},
        ],
        "columns": [
            ("month", "月份"), ("category", "品类"), ("product_id", "商品编号"),
            ("product_name", "商品名称"), ("quantity", "销量"), ("revenue", "收入"), ("gross_profit", "毛利"),
        ],
        "run": _run_product_month,
    },
    "expense_dept_month": {
        "title": "部门费用月历",
        "description": "月 × 部门 × 费用类别（分摊后口径）。口径出处：mart_expense_dept_month。",
        "params": [{"name": "months", "label": "最近完整月数", "type": "number", "default": 12}],
        "columns": [
            ("month", "月份"), ("dept_code", "部门编码"), ("dept_name", "部门名称"),
            ("category", "费用类别"), ("allocated_amount", "分摊费用"),
        ],
        "run": _run_expense_dept,
    },
}


def list_reports() -> list[dict]:
    return [
        {"key": k, "title": r["title"], "description": r["description"], "params": r["params"]}
        for k, r in REPORTS.items()
    ]


def get_report(key: str) -> dict:
    if key not in REPORTS:
        raise KeyError(key)
    return REPORTS[key]


def run_report(key: str, params: dict) -> tuple[list[tuple[str, str]], list[dict]]:
    """返回 (列标签, 行数据)"""
    rep = get_report(key)
    sql, bind = rep["run"](params)
    df = duck.query_df(sql, bind)
    if df is None or len(df) == 0:
        return rep["columns"], []
    df.columns = [c.lower() for c in df.columns]
    rows = duck.df_to_dicts(df)
    return rep["columns"], rows


def report_options() -> dict:
    """筛选器的候选项"""
    try:
        return {
            "region": _distinct("region_code", "marts.mart_region_month"),
            "level": _distinct("customer_level", "marts.mart_customer_summary"),
            "category": _distinct("category", "marts.mart_product_month"),
        }
    except Exception:
        return {"region": [], "level": [], "category": []}
