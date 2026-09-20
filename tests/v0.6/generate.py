# -*- coding: utf-8 -*-
"""tests/v0.6 —— 测试实例 _wb_r1（配置工作台验收场景）确定性生成器。

用法（仓库根目录）：
    .venv/Scripts/python.exe tests/v0.6/generate.py

行为：幂等重建 instances/_wb_r1/（六份 YAML 配置 + data/inbox/*.csv）。
  - 全部内容为固定常量，无时间戳、无随机数：同输入双跑逐字节一致；
  - CSV 一律 utf-8-sig（带 BOM），行内容与播种违规清单见 tests/v0.6/SPEC.md；
  - 重建前先删除既有 instances/_wb_r1/ 目录（保证无残留文件）；
  - 不触碰 data/warehouse/_wb_r1.duckdb（由三步链的 ingest_run 创建/覆盖）。

场景设计：零售进销存形态的最小账套（5 源 92 行），故意播种 9 类契约违规
（全部 yellow 级，保证三步链退出码为 0），详见 SPEC.md 的播种表 V1~V9。
"""
from __future__ import annotations

import csv
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # 仓库根
INST = ROOT / "instances" / "_wb_r1"
INBOX = INST / "data" / "inbox"

# ---------------------------------------------------------------- 六份 YAML 配置
INSTANCE_YML = """\
# 测试实例 _wb_r1 —— 配置工作台验收（零售进销存形态）
# 由 tests/v0.6/generate.py 生成：请勿手改，重建请重跑生成器。
name: _wb_r1
title: 工作台测试账套R1（零售进销存形态）
inbox: data/inbox
database: ../../../data/warehouse/_wb_r1.duckdb
tz: Asia/Shanghai
"""

SOURCES_YML = """\
# 测试实例 _wb_r1 —— 入口档案 + 字段契约（契约语义依据 docs/待确认与决策.md D15）
# 播种违规：V1 渠道枚举 / V2 数量范围 / V3 单价类型 / V4 单据号必填 / V9 品类枚举 / V8 快照范围
# 由 tests/v0.6/generate.py 生成：请勿手改，重建请重跑生成器。
version: 1

sources:
  - name: fact_ledger
    title: 进销存台账
    discover:
      patterns: ["台账_*.csv"]
      encodings: [utf-8-sig, gbk]
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 事项类型, map: entry_type,    type: string,  required: true, level: yellow, enum: [销售, 采购, 采购退货, 期末库存]}
      - {cn: 单据号,   map: doc_no,        type: string,  required: true, level: yellow}
      - {cn: 单据日期, map: doc_date,      type: date,    required: true, level: yellow}
      - {cn: 门店编码, map: store_code,    type: string,  required: true, level: yellow}
      - {cn: 商品编码, map: product_code,  type: string,  required: true, level: yellow}
      - {cn: 供应商编码, map: supplier_code, type: string}
      - {cn: 渠道,     map: channel,       type: string,  enum: [门店, 电商], level: yellow}
      - {cn: 数量,     map: quantity,      type: integer, range: [1, 999], level: yellow}
      - {cn: 单价,     map: unit_price,    type: decimal, level: yellow}
      - {cn: 折扣率,   map: discount_rate, type: decimal, range: [0, 1], level: yellow, missing: default, default: 0}
      - {cn: 期末数量, map: ending_qty,    type: integer, range: [0, 1000000], level: yellow}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red

  - name: stock_snapshot
    title: 库存快照
    discover:
      patterns: ["库存快照_*.csv"]
      encodings: [utf-8-sig, gbk]
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 快照月份, map: snap_month,   type: string}
      - {cn: 快照日期, map: snap_date,    type: date,    required: true, level: yellow}
      - {cn: 门店编码, map: store_code,   type: string,  required: true, level: yellow}
      - {cn: 商品编码, map: product_code, type: string,  required: true, level: yellow}
      - {cn: 期末数量, map: ending_qty,   type: integer, required: true, level: yellow, range: [0, 100000]}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red

  - name: stores
    title: 门店
    discover:
      patterns: ["门店_*.csv"]
      encodings: [utf-8-sig]
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 门店编码, map: store_code,  type: string, required: true, level: yellow}
      - {cn: 门店名称, map: store_name,  type: string}
      - {cn: 城市,     map: city,        type: string}
      - {cn: 大区,     map: region_name, type: string, enum: [华东, 华北, 华南], level: yellow}
      - {cn: 开业日期, map: open_date,   type: date}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red

  - name: products
    title: 商品
    discover:
      patterns: ["商品_*.csv"]
      encodings: [utf-8-sig]
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 商品编码, map: product_code, type: string, required: true, level: yellow}
      - {cn: 商品名称, map: product_name, type: string}
      - {cn: 品类,     map: category,     type: string, enum: [食品, 百货, 日化], level: yellow}
      - {cn: 单位,     map: unit,         type: string}
      - {cn: 标准成本, map: std_cost,      type: decimal, level: yellow}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red

  - name: suppliers
    title: 供应商
    discover:
      patterns: ["供应商_*.csv"]
      encodings: [utf-8-sig]
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 供应商编码, map: supplier_code, type: string, required: true, level: yellow}
      - {cn: 供应商名称, map: supplier_name, type: string}
      - {cn: 结算方式,   map: settle_type,   type: string, enum: [月结30, 月结60, 现结], level: yellow}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red
"""

WIDE_YML = """\
# 测试实例 _wb_r1 —— 声明式宽表（join 契约：V6 供应商匹空 / V7 门店扇出，均定级 yellow）
# 由 tests/v0.6/generate.py 生成：请勿手改，重建请重跑生成器。
version: 1
wide:
  name: wide_ledger
  main: fact_ledger
  joins:
    - table: stores
      keys: {left: store_code, right: store_code}
      how: left
      columns: [store_name, city, region_name]
      contract: {fanout: yellow, null_match: yellow, orphan_right: ignore}
    - table: products
      keys: {left: product_code, right: product_code}
      how: left
      columns: [product_name, category, std_cost]
      contract: {fanout: yellow, null_match: yellow, orphan_right: ignore}
    - table: suppliers
      keys: {left: supplier_code, right: supplier_code}
      how: left
      columns: [supplier_name]
      contract: {fanout: yellow, null_match: yellow, orphan_right: ignore}
  derived:
    - {name: sales_net,    expr: "case when entry_type = '销售' then round(quantity * unit_price * (1 - discount_rate), 2) else 0 end", desc: "销售行折后金额 = 数量×单价×(1−折扣率)"}
    - {name: sales_cost,   expr: "case when entry_type = '销售' then round(quantity * std_cost, 2) else 0 end", desc: "销售行成本 = 数量×标准成本"}
    - {name: gross_profit, expr: "case when entry_type = '销售' then round(quantity * unit_price * (1 - discount_rate) - quantity * std_cost, 2) else 0 end", desc: "销售行毛利 = 折后金额 − 成本"}
    - {name: ecomm_net,    expr: "case when entry_type = '销售' and channel = '电商' then round(quantity * unit_price * (1 - discount_rate), 2) else 0 end", desc: "电商渠道销售行折后金额"}
    - {name: purchase_amt, expr: "case when entry_type = '采购' then round(quantity * unit_price, 2) else 0 end", desc: "采购行金额 = 数量×采购单价"}
    - {name: stock_qty,    expr: "case when entry_type = '期末库存' then coalesce(ending_qty, 0) else 0 end", desc: "期末库存行数量"}
  drop: [_source_file, _loaded_at]
"""

DIMENSIONS_YML = """\
# 测试实例 _wb_r1 —— 维度声明（商品 product_code 有意不被任何报表引用 → impact 应映射 []）
# 由 tests/v0.6/generate.py 生成：请勿手改，重建请重跑生成器。
version: 1
dimensions:
  - {name: 月份,   column: doc_date,      type: time, grain: month}
  - {name: 大区,   column: region_name,   type: category}
  - {name: 城市,   column: city,          type: category}
  - {name: 门店,   column: store_name,    type: category}
  - {name: 品类,   column: category,      type: category}
  - {name: 渠道,   column: channel,       type: category}
  - {name: 供应商, column: supplier_name, type: category}
  - {name: 商品,   column: product_code,  type: category}
"""

METRICS_YML = """\
# 测试实例 _wb_r1 —— 指标口径唯一出处（电商销售占比 有意不被任何报表引用 → impact 应映射 []）
# 由 tests/v0.6/generate.py 生成：请勿手改，重建请重跑生成器。
version: 1
metrics:
  - {name: 销售额,       expr: "sum(sales_net)", desc: "折后销售合计 = 数量×单价×(1−折扣率)，仅销售行"}
  - {name: 销售成本,     expr: "sum(sales_cost)", desc: "数量×商品标准成本 合计，仅销售行"}
  - {name: 毛利,         expr: "sum(gross_profit)", desc: "销售额 − 销售成本"}
  - {name: 毛利率,       expr: "round(sum(gross_profit) / nullif(sum(sales_net), 0), 4)", format: percent, desc: "毛利 ÷ 销售额；销售额为 0 时为空"}
  - {name: 采购额,       expr: "sum(purchase_amt)", desc: "采购行 数量×采购单价 合计"}
  - {name: 期末库存量,   expr: "sum(stock_qty)", desc: "期末库存行数量合计"}
  - {name: 电商销售占比, expr: "round(sum(ecomm_net) / nullif(sum(sales_net), 0), 4)", format: percent, desc: "电商渠道销售额 ÷ 总销售额"}
"""

DASHBOARD_YML = """\
# 测试实例 _wb_r1 —— 报表声明（六张报表覆盖 dimension/time_dim/filters 三类引用 + 未引用指标/维度）
# 由 tests/v0.6/generate.py 生成：请勿手改，重建请重跑生成器。
version: 1
reports:
  - key: monthly_kpi
    title: 月度经营总览
    dimension: 月份
    metrics: [销售额, 毛利, 毛利率]
    chart: bar_line
    full_period_only: true
  - key: region_month
    title: 大区月报
    dimension: 大区
    time_dim: 月份
    metrics: [销售额, 毛利]
    filters: [城市]
    chart: stack_bar
    full_period_only: true
  - key: category_month
    title: 品类月报
    dimension: 品类
    time_dim: 月份
    metrics: [销售额, 销售成本, 毛利率]
    chart: stack_bar
    full_period_only: true
  - key: channel_month
    title: 渠道月报
    dimension: 渠道
    time_dim: 月份
    metrics: [销售额, 毛利]
    chart: stack_bar
    full_period_only: true
  - key: store_rank
    title: 门店排行
    dimension: 门店
    metrics: [销售额, 毛利, 期末库存量]
    filters: [大区, 城市]
    chart: hbar
  - key: supplier_rank
    title: 供应商采购排行
    dimension: 供应商
    metrics: [采购额]
    chart: hbar
"""

# ---------------------------------------------------------------- inbox CSV 数据
# 列序必须与 sources.yml 各源 fields 的 cn 顺序逐列一致（header_changed: red）。
FACT_HEADER = ["事项类型", "单据号", "单据日期", "门店编码", "商品编码", "供应商编码", "渠道", "数量", "单价", "折扣率", "期末数量"]

# 销售行（21 行干净 + 3 行 S05 供应商回填 + 3 行 V1 枚举违规 + 1 行 V3 类型违规 + 1 行 V4a 必填违规）
# 元组序：单据号, 单据日期, 门店, 商品, 供应商, 渠道, 数量, 单价, 折扣率
_SALES = [
    ("SZ-2607-001", "2026-07-01", "S01", "FP001", "", "门店", "12", "3.60", "0"),
    ("SZ-2607-002", "2026-07-01", "S01", "FP002", "", "门店", "8",  "6.50", ""),    # V5 折扣缺失→默认0
    ("SZ-2607-003", "2026-07-02", "S01", "BB001", "", "电商", "5",  "10.20", "0.1"),
    ("SZ-2607-004", "2026-07-05", "S02", "FP001", "", "门店", "6",  "3.55", ""),    # V5
    ("SZ-2607-005", "2026-07-06", "S02", "PC002", "", "电商", "10", "4.50", "0"),
    ("SZ-2607-006", "2026-07-08", "S02", "BB003", "", "门店", "15", "2.00", "0.1"),
    ("SZ-2607-007", "2026-07-10", "S03", "FP003", "", "门店", "2",  "13.80", "0"),
    ("SZ-2607-008", "2026-07-12", "S03", "BB001", "", "电商", "4",  "10.50", "0.2"),
    ("SZ-2607-009", "2026-07-15", "S03", "PC004", "", "门店", "11", "5.20", ""),    # V5
    ("SZ-2607-010", "2026-07-18", "S04", "BB002", "", "门店", "25", "2.60", "0"),
    ("SZ-2607-011", "2026-07-20", "S04", "PC001", "", "电商", "2",  "17.00", ""),   # V5
    ("SZ-2607-012", "2026-07-22", "S04", "FP002", "", "门店", "14", "6.40", "0.1"),
    ("SZ-2607-013", "2026-07-25", "S05", "FP001", "GY001", "门店", "9",  "3.50", "0"),   # V7 扇出行
    ("SZ-2607-014", "2026-07-20", "S04", "FP001", "", "门店", "10", "N/A", "0"),         # V3 类型违规（预期被剔）
    ("SZ-2608-001", "2026-08-01", "S01", "PC001", "", "门店", "3",  "16.80", "0.15"),
    ("SZ-2608-002", "2026-08-02", "S01", "BB002", "", "电商", "20", "2.80", ""),    # V5
    ("SZ-2608-003", "2026-08-03", "S01", "FP003", "", "门店", "4",  "13.50", "0"),
    ("SZ-2608-004", "2026-08-05", "S02", "FP002", "", "门店", "7",  "6.60", ""),    # V5
    ("SZ-2608-005", "2026-08-08", "S02", "PC003", "", "电商", "9",  "3.30", "0"),
    ("SZ-2608-006", "2026-08-10", "S03", "FP001", "", "门店", "18", "3.45", "0"),
    ("SZ-2608-007", "2026-08-12", "S03", "PC006", "", "电商", "6",  "4.10", "0.1"),
    ("SZ-2608-008", "2026-08-15", "S04", "BB003", "", "门店", "30", "1.90", "0"),
    ("SZ-2608-009", "2026-08-18", "S04", "PC002", "", "电商", "8",  "4.60", "0.15"),
    ("SZ-2608-010", "2026-08-06", "S05", "BB001", "GY001", "门店", "3",  "10.80", "0.1"),  # V7 扇出行
    ("SZ-2608-011", "2026-08-09", "S05", "PC001", "GY001", "电商", "5",  "16.90", "0"),    # V7 扇出行
    ("SZ-2608-012", "2026-08-05", "S01", "FP002", "", "团购", "6",  "6.55", "0"),          # V1 枚举违规
    ("SZ-2608-013", "2026-08-06", "S02", "PC001", "", "团购", "4",  "17.10", "0.1"),       # V1
    ("SZ-2608-014", "2026-08-07", "S03", "BB002", "", "团购", "12", "2.70", "0"),          # V1
    ("",            "2026-08-20", "S01", "PC003", "", "门店", "5",  "3.40", "0"),          # V4a 必填违规（预期被剔）
]

# 采购行（8 干净 + 2 行 V2 范围违规 + 1 行 V4b 必填违规）
_PURCHASE = [
    ("PO-2607-001", "2026-07-03", "S01", "FP001", "GY001", "100",  "3.10"),
    ("PO-2607-002", "2026-07-05", "S02", "BB001", "GY003", "60",   "9.50"),
    ("PO-2607-003", "2026-07-12", "S03", "PC001", "GY002", "80",   "15.00"),
    ("PO-2607-004", "2026-07-15", "S03", "BB001", "GY004", "2000", "9.80"),   # V2b 范围越界（>999）
    ("PO-2608-001", "2026-08-02", "S01", "FP002", "GY004", "50",   "5.80"),
    ("PO-2608-002", "2026-08-04", "S02", "PC002", "GY005", "120",  "3.90"),
    ("PO-2608-003", "2026-08-08", "S04", "BB002", "GY001", "200",  "2.20"),
    ("PO-2608-004", "2026-08-10", "S03", "FP003", "GY002", "40",   "12.00"),
    ("PO-2608-005", "2026-08-14", "S01", "PC004", "GY003", "70",   "4.60"),
    ("PO-2608-006", "2026-08-10", "S01", "FP001", "GY002", "0",    "3.20"),   # V2a 范围越界（<1）
    ("",            "2026-08-12", "S02", "PC003", "GY003", "30",   "3.05"),   # V4b 必填违规（预期被剔）
]

# 采购退货行（4 行干净）
_RETURN = [
    ("RT-2607-001", "2026-07-20", "S01", "BB001", "GY003", "2", "9.60"),
    ("RT-2607-002", "2026-07-28", "S02", "PC002", "GY005", "3", "4.00"),
    ("RT-2608-001", "2026-08-15", "S03", "FP001", "GY001", "5", "3.30"),
    ("RT-2608-002", "2026-08-20", "S04", "PC004", "GY002", "1", "4.80"),
]

# 期末库存行（5 行；供应商/渠道/数量/单价/折扣率留空，期末数量回填）
_INVENTORY = [
    ("QM-2608-001", "2026-08-31", "S01", "FP001", "320"),
    ("QM-2608-002", "2026-08-31", "S02", "FP002", "150"),
    ("QM-2608-003", "2026-08-31", "S03", "BB001", "88"),
    ("QM-2608-004", "2026-08-31", "S04", "PC001", "66"),
    ("QM-2608-005", "2026-08-31", "S05", "FP003", "41"),   # V7 扇出行（S05）
]


def _fact_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for doc_no, d, store, prod, sup, ch, qty, price, disc in _SALES:
        rows.append(["销售", doc_no, d, store, prod, sup, ch, qty, price, disc, ""])
    for doc_no, d, store, prod, sup, qty, price in _PURCHASE:
        rows.append(["采购", doc_no, d, store, prod, sup, "门店", qty, price, "", ""])
    for doc_no, d, store, prod, sup, qty, price in _RETURN:
        rows.append(["采购退货", doc_no, d, store, prod, sup, "门店", qty, price, "", ""])
    for doc_no, d, store, prod, end_qty in _INVENTORY:
        rows.append(["期末库存", doc_no, d, store, prod, "", "", "", "", "", end_qty])
    return rows


STORES_HEADER = ["门店编码", "门店名称", "城市", "大区", "开业日期"]
# V7 播种：S05 出现两行（右表键重复 → join 扇出）。门店编码有意不声明 unique（SCD 形态）。
STORES = [
    ["S01", "旗舰一店",     "上海", "华东", "2024-01-01"],
    ["S02", "旗舰二店",     "杭州", "华东", "2024-03-15"],
    ["S03", "京城一店",     "北京", "华北", "2024-06-01"],
    ["S04", "羊城一店",     "广州", "华南", "2024-09-09"],
    ["S05", "社区五店",     "上海", "华东", "2025-01-20"],
    ["S05", "社区五店二号", "上海", "华东", "2025-02-01"],
]

PRODUCTS_HEADER = ["商品编码", "商品名称", "品类", "单位", "标准成本"]
# V9 播种：FP009 品类=生鲜（枚举未命中）；FP009 有意不被任何台账行引用（orphan_right: ignore，零行）
PRODUCTS = [
    ["FP001", "苏打饼干", "食品", "件", "3.50"],
    ["FP002", "核桃乳",   "食品", "件", "6.20"],
    ["FP003", "牛肉干",   "食品", "袋", "12.80"],
    ["BB001", "洗衣液",   "百货", "瓶", "9.90"],
    ["BB002", "抽纸",     "百货", "包", "2.50"],
    ["BB003", "垃圾袋",   "百货", "卷", "1.80"],
    ["PC001", "洗发水",   "日化", "瓶", "15.60"],
    ["PC002", "牙膏",     "日化", "支", "4.30"],
    ["PC003", "香皂",     "日化", "块", "3.10"],
    ["PC004", "洗洁精",   "日化", "瓶", "5.00"],
    ["PC006", "毛巾",     "日化", "条", "4.00"],
    ["FP009", "有机蔬菜", "生鲜", "份", "8.80"],
]

SUPPLIERS_HEADER = ["供应商编码", "供应商名称", "结算方式"]
SUPPLIERS = [
    ["GY001", "康泰食品", "月结30"],
    ["GY002", "洁丽日化", "月结30"],
    ["GY003", "百汇商贸", "月结60"],
    ["GY004", "鲜丰农业", "现结"],
    ["GY005", "晨光百货", "月结60"],
]

SNAP_HEADER = ["快照月份", "快照日期", "门店编码", "商品编码", "期末数量"]
# V8 播种：最后一行 期末数量=-5（范围越界）。其余 20 行 = 5 店 × 4 商品的确定性网格。
_SNAP_GRID = [
    ("FP001", [120, 96, 210, 44, 18]),
    ("FP002", [88, 61, 150, 37, 12]),
    ("BB001", [66, 40, 132, 29, 9]),
    ("PC001", [54, 33, 98, 21, 7]),
]
_SNAP_BAD = ["2026-08", "2026-08-31", "S01", "BB003", "-5"]   # V8 范围违规（<0）


def _snap_rows() -> list[list[str]]:
    rows = []
    for prod, qtys in _SNAP_GRID:
        for store, qty in zip(["S01", "S02", "S03", "S04", "S05"], qtys):
            rows.append(["2026-08", "2026-08-31", store, prod, str(qty)])
    rows.append(_SNAP_BAD)
    return rows


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def main() -> None:
    if INST.exists():
        shutil.rmtree(INST)
    INBOX.mkdir(parents=True, exist_ok=True)

    files = {
        "instance.yml": INSTANCE_YML,
        "sources.yml": SOURCES_YML,
        "wide.yml": WIDE_YML,
        "dimensions.yml": DIMENSIONS_YML,
        "metrics.yml": METRICS_YML,
        "dashboard.yml": DASHBOARD_YML,
    }
    for name, text in files.items():
        (INST / name).write_text(text, encoding="utf-8", newline="\n")

    _write_csv(INBOX / "台账_202608.csv", FACT_HEADER, _fact_rows())
    _write_csv(INBOX / "库存快照_202608.csv", SNAP_HEADER, _snap_rows())
    _write_csv(INBOX / "门店_202608.csv", STORES_HEADER, STORES)
    _write_csv(INBOX / "商品_202608.csv", PRODUCTS_HEADER, PRODUCTS)
    _write_csv(INBOX / "供应商_202608.csv", SUPPLIERS_HEADER, SUPPLIERS)

    print("已重建", INST.relative_to(ROOT))
    for p in sorted(INST.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(INST)}  {p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
