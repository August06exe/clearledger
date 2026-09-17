# -*- coding: utf-8 -*-
"""明账 ClearLedger — 演示数据生成器

生成一套仿真的公司管理报表底层数据，落入 data/inbox/（门户的"数据投放区"）：

  sales_transactions.csv  销售流水（订单级，~17万行）
  customers.xlsx          客户主数据 + 业务标签（行业/等级/区域/状态）
  products.xlsx           商品主数据（含标准成本）
  org_structure.csv       组织架构（集团-事业部-职能）
  expenses.xlsx           部门月度费用流水

数据特性：
  - 2025-04 ~ 2026-09 共 18 个自然月，含增长趋势、季节性、周末效应
  - 预埋一处数据异常：2026-05 华东区收入骤降（当月 19 日起无数据），
    用于演示门户"黄灯 = 数据质量告警"
  - 少量脏数据：客户编号带首尾空格、部分折扣率缺失，用于演示清洗层

用法：.venv/Scripts/python sample_data/generate.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

rng = np.random.default_rng(42)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "inbox"
OUT.mkdir(parents=True, exist_ok=True)

START = date(2025, 4, 1)
END = date.today() - timedelta(days=1)  # 动态截止到昨天，保证"数据新鲜度"演示始终是绿的

# ---------------------------------------------------------------- 维度数据
REGIONS = [
    ("R01", "华东", ["上海", "杭州", "南京", "苏州", "宁波"], 0.32),
    ("R02", "华北", ["北京", "天津", "济南", "青岛"], 0.22),
    ("R03", "华南", ["广州", "深圳", "厦门", "佛山"], 0.20),
    ("R04", "华中", ["武汉", "长沙", "郑州"], 0.14),
    ("R05", "西南", ["成都", "重庆", "昆明"], 0.12),
]
INDUSTRIES = ["制造业", "零售连锁", "互联网", "教育培训", "医疗健康", "金融服务"]
LEVELS = [("战略客户", 0.06, 3.0), ("大客户", 0.18, 2.0), ("中型客户", 0.36, 1.2), ("小微企业", 0.40, 0.6)]
SUFFIX = ["科技", "贸易", "制造", "实业", "电子", "智能", "供应链"]

CATEGORIES = {
    "智能硬件": [("智能网关 G2", 1299, 820), ("边缘计算盒 E4", 2580, 1610), ("工业平板 T10", 3299, 2140),
                 ("智能巡检机器人", 18900, 12300), ("车载定位终端", 399, 210), ("智能门禁一体机", 899, 520)],
    "软件订阅": [("财务套件·年费", 9800, 1500), ("数据中台基础版·年费", 19800, 3600), ("RPA流程机器人·年费", 12800, 2600),
                 ("低代码平台企业版·年费", 26800, 5200), ("AI质检模块·年费", 15800, 3400)],
    "耗材配件": [("热敏打印纸箱(50卷)", 320, 190), ("碳带套装", 260, 150), ("设备支架", 129, 62),
                 ("电源适配器 65W", 89, 41), ("数据线束包", 149, 74), ("标签纸卷", 99, 47)],
    "专业服务": [("实施交付·人天", 2800, 1500), ("年度运维·次", 6800, 3200), ("数据治理咨询·人天", 4800, 2400), ("培训认证·人", 1980, 800)],
    "延保服务": [("硬件延保2年", 1500, 480), ("软件续费折扣包", 2200, 700), ("上门服务包·年", 3600, 1300)],
}
CAT_PREFIX = {"智能硬件": "HW", "软件订阅": "SW", "耗材配件": "AC", "专业服务": "SV", "延保服务": "EX"}
CAT_WEIGHT = {"智能硬件": 0.34, "软件订阅": 0.18, "耗材配件": 0.26, "专业服务": 0.14, "延保服务": 0.08}

DEPTS = [
    ("D00", "集团总部", "", 1, "否", ""),
    ("D01", "华东事业部", "D00", 2, "是", "R01"),
    ("D02", "华北事业部", "D00", 2, "是", "R02"),
    ("D03", "华南事业部", "D00", 2, "是", "R03"),
    ("D04", "华中事业部", "D00", 2, "是", "R04"),
    ("D05", "西南事业部", "D00", 2, "是", "R05"),
    ("D101", "财务部", "D00", 2, "否", ""),
    ("D102", "人力行政部", "D00", 2, "否", ""),
    ("D103", "技术与研发部", "D00", 2, "否", ""),
]
# 各部门费用科目（月度基准额，元）
SALES_EXP = [("人力成本", 300000), ("市场推广", 150000), ("差旅费", 55000), ("办公租金", 80000), ("其他", 20000)]
HQ_EXP = {
    "D101": [("人力成本", 180000), ("办公租金", 40000), ("其他", 8000)],
    "D102": [("人力成本", 220000), ("办公租金", 35000), ("其他", 12000)],
    "D103": [("人力成本", 520000), ("研发投入", 260000), ("办公租金", 60000), ("其他", 15000)],
}
SEASON = {1: 0.9, 2: 1.05, 3: 1.0, 4: 1.0, 5: 1.05, 6: 0.95,
          7: 0.9, 8: 1.0, 9: 1.15, 10: 1.30, 11: 1.35, 12: 1.10}
DISCOUNTS = np.array([[0.0, 0.50], [0.02, 0.17], [0.05, 0.16], [0.10, 0.10], [0.15, 0.05], [0.20, 0.02]])


def build_products() -> pd.DataFrame:
    rows, pid = [], 1
    for cat, items in CATEGORIES.items():
        for name, price, cost in items:
            rows.append(dict(商品编号=f"{CAT_PREFIX[cat]}{pid:03d}", 商品名称=name, 品类=cat,
                             单位="件", 标准单价=float(price), 标准成本=float(cost)))
            pid += 1
    return pd.DataFrame(rows)


def build_customers() -> pd.DataFrame:
    rows, used = [], set()
    region_codes = [r[0] for r in REGIONS]
    region_p = np.array([r[3] for r in REGIONS])
    city_of = {r[0]: r[2] for r in REGIONS}
    ind_short = {"制造业": "制造", "零售连锁": "商贸", "互联网": "网络", "教育培训": "教育", "医疗健康": "医疗", "金融服务": "金融"}
    for i in range(1, 181):
        cid = f"C{i:04d}"
        rc = str(rng.choice(region_codes, p=region_p))
        city = str(rng.choice(city_of[rc]))
        ind = str(rng.choice(INDUSTRIES))
        for s in rng.permutation(SUFFIX):
            name = f"{city}{ind_short[ind]}{s}"
            if name not in used:
                used.add(name)
                break
        else:
            name = f"{city}{ind_short[ind]}企业{i:03d}"
        li = int(rng.choice(len(LEVELS), p=[l[1] for l in LEVELS]))
        status = "流失" if rng.random() < 0.05 else "活跃"
        rows.append(dict(客户编号=cid, 客户名称=name, 行业=ind, 客户等级=LEVELS[li][0],
                         区域编码=rc, 区域=[r[1] for r in REGIONS if r[0] == rc][0],
                         状态=status, _churn_month=int(rng.integers(11, 17))))
    return pd.DataFrame(rows)


def build_sales(products: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    # 抽样权重
    prod_p = np.array([CAT_WEIGHT[c] for c in products["品类"]])
    prod_p = prod_p / prod_p.sum()
    prod_p = prod_p * (1 + rng.random(len(products)) * 0.3)
    prod_p = prod_p / prod_p.sum()

    lvl_p = np.array([LEVELS[[l[0] for l in LEVELS].index(x)][2] for x in customers["客户等级"]])
    cust_p = lvl_p * (0.6 + rng.random(len(customers)) * 0.8)
    cust_p = cust_p / cust_p.sum()

    cust_recs = customers.to_dict("records")
    prod_recs = products.to_dict("records")

    rows, d = [], START
    while d <= END:
        month_t = (d.year - 2025) * 12 + (d.month - 4)          # 2025-04 -> 0
        weekday_f = 0.35 if d.weekday() >= 5 else 1.0
        base = 380 * (1.012 ** month_t) * SEASON[d.month] * weekday_f
        is_anomaly = (d.year == 2026 and d.month == 5)          # 预埋异常：华东 5 月断供
        for _ in range(int(rng.poisson(base))):
            c = cust_recs[int(rng.choice(len(cust_recs), p=cust_p))]
            if c["状态"] == "流失" and month_t >= c["_churn_month"]:
                continue
            if is_anomaly and c["区域编码"] == "R01":
                if d.day >= 19:
                    continue
                if rng.random() < 0.55:
                    continue
            p = prod_recs[int(rng.choice(len(prod_recs), p=prod_p))]
            qty = int(1 + rng.poisson(5))
            price = round(p["标准单价"] * (0.95 + rng.random() * 0.10), 2)
            disc = float(rng.choice(DISCOUNTS[:, 0], p=DISCOUNTS[:, 1]))
            disc = np.nan if rng.random() < 0.0005 else disc     # 少量折扣率缺失 → 清洗层补 0
            rows.append((f"SO-{d:%Y%m%d}-{len(rows) + 1:07d}", d.isoformat(),
                         c["客户编号"], p["商品编号"], qty, price, disc, round(qty * price, 2)))
        d += timedelta(days=1)

    df = pd.DataFrame(rows, columns=["订单号", "订单日期", "客户编号", "商品编号", "数量", "单价", "折扣率", "金额"])
    dirty = rng.choice(len(df), 300, replace=False)             # 脏数据：客户编号首尾空格
    df.loc[dirty, "客户编号"] = " " + df.loc[dirty, "客户编号"] + " "
    return df


def build_expenses() -> pd.DataFrame:
    rows = []
    months = pd.period_range("2025-04", "2026-09", freq="M")
    region_p = np.array([r[3] for r in REGIONS])
    for i, m in enumerate(months):
        t = 1.008 ** i
        me = f"{m.year:04d}-{m.month:02d}-{m.days_in_month:02d}"
        for code, name, _, _, is_sales, rc in DEPTS:
            if code == "D00":
                continue  # 集团总部为虚拟节点，自身无费用（职能费用在 D101~D103）
            if is_sales == "是":
                scale = region_p[[r[0] for r in REGIONS].index(rc)] / 0.20
                for cat, amt in SALES_EXP:
                    amt = amt * t * scale * SEASON[m.month] * (0.9 + rng.random() * 0.2)
                    rows.append((me, code, name, cat, round(float(amt), 2)))
            else:
                for cat, amt in HQ_EXP[code]:
                    amt = amt * t * (0.9 + rng.random() * 0.2)
                    rows.append((me, code, name, cat, round(float(amt), 2)))
    return pd.DataFrame(rows, columns=["记账日期", "部门编码", "部门名称", "费用类别", "金额"])


def build_org() -> pd.DataFrame:
    return pd.DataFrame(DEPTS, columns=["部门编码", "部门名称", "上级部门编码", "层级", "是否销售部门", "负责区域编码"])


def main() -> None:
    products = build_products()
    customers = build_customers()
    sales = build_sales(products, customers)
    expenses = build_expenses()
    org = build_org()

    customers_out = customers.drop(columns=["_churn_month"])
    sales.to_csv(OUT / "sales_transactions.csv", index=False, encoding="utf-8-sig")
    customers_out.to_excel(OUT / "customers.xlsx", index=False, engine="xlsxwriter")
    products.to_excel(OUT / "products.xlsx", index=False, engine="xlsxwriter")
    org.to_csv(OUT / "org_structure.csv", index=False, encoding="utf-8-sig")
    expenses.to_excel(OUT / "expenses.xlsx", index=False, engine="xlsxwriter")

    # ------- 摘要与自检 -------
    sales["_m"] = sales["订单日期"].str[:7]
    rev = (sales["_m"]).value_counts().sort_index()
    r01 = sales[sales["客户编号"].isin(customers[customers["区域编码"] == "R01"]["客户编号"])]
    r01m = r01["_m"].value_counts().sort_index()
    print("=" * 60)
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name:28s} {f.stat().st_size / 1024:10.1f} KB")
    print("=" * 60)
    print(f"销售流水行数: {len(sales):,}")
    print(f"月度收入(万元): 最近6个月 = {[round(v / 1e4) for v in rev.tail(6)]}")
    a4, a5 = r01m.get('2026-04', 0), r01m.get('2026-05', 0)
    print(f"异常自检: 华东 2026-05 销售行数 {a5:,} vs 2026-04 {a4:,} → 降幅 {(a5 - a4) / max(a4, 1) * 100:.0f}% (期望约 -55%)")
    print("生成完毕 →", OUT)


if __name__ == "__main__":
    main()
