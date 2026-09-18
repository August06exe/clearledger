# -*- coding: utf-8 -*-
"""S1 荟品汇零售连锁：数据生成器 + 混沌注入 + 密封标准答案（命题方出品）

产出：
  1. instances/retail/data/inbox/  下 9 个源文件 + 1 个诱饵文件（混沌 A11）
  2. tests/v0.4/S1_retail/expected/answer.json       （六张报表密封答案）
  3. tests/v0.4/S1_retail/expected/manifest.sha256   （answer.json 的 SHA256）

确定性：固定 seed，重复运行逐字节复现。
答案独立于引擎：纯 pandas/Decimal 按 SPEC §7.1 契约裁决模拟"契约处理后的真相"再聚合。
用法：.venv/Scripts/python.exe tests/v0.4/S1_retail/generate.py [输出目录]
"""
from __future__ import annotations

import calendar
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260919
rng = np.random.default_rng(SEED)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                       # 仓库根
_ARGS = sys.argv[1:]
DEEP = "--deep" in _ARGS                     # 轮4 加深口径：注入加深混沌并重密封答案
_POS = [a for a in _ARGS if not a.startswith("--")]
OUT = Path(_POS[0]) if _POS else ROOT / "instances" / "retail" / "data" / "inbox"
EXPECTED = HERE / "expected"

MONTHS = [(y, m) for y in (2025, 2026) for m in range(1, 13)
          if (y == 2025 and m >= 9) or (y == 2026 and m <= 8)]          # 12 个完整月
MONTH_KEYS = [f"{y}-{m:02d}" for y, m in MONTHS]

# ---------------------------------------------------------------- 主数据（SPEC §1，硬编码）
STORES = [  # 编码, 名称, 城市, 大区, 客流权重, 开业日期
    ("HD01", "上海人民广场店", "上海", "华东", 1.50, "2021-03-01"),
    ("HD02", "杭州西湖店",     "杭州", "华东", 1.10, "2021-09-17"),
    ("HD03", "南京新街口店",   "南京", "华东", 1.00, "2022-04-02"),
    ("HB01", "北京国贸店",     "北京", "华北", 1.30, "2022-11-11"),
    ("HB02", "天津滨江道店",   "天津", "华北", 0.90, "2023-05-20"),
    ("HB03", "北京朝阳店（筹备）", "北京", "华北", 0.0, "2026-10-01"),   # A13：零流水
    ("HN01", "广州天河店",     "广州", "华南", 1.20, "2023-01-08"),
    ("HN02", "深圳福田店",     "深圳", "华南", 1.15, "2023-08-18"),
    ("HN03", "厦门中山路店",   "厦门", "华南", 0.75, "2024-02-14"),
]
OPERATING = [s for s in STORES if s[0] != "HB03"]

CAT_SPEC = {  # 品类: (前缀, 数量, 成本区间, 单位, 基础词库, 规格词库)
    "食品": ("FP", 50, (3.0, 30.0), ["袋", "瓶", "盒"],
            ["全麦吐司", "鲜牛奶", "原味酸奶", "苏打饼干", "牛肉干", "薯片", "每日坚果", "沙琪玛",
             "蛋黄派", "午餐肉罐头", "八宝粥", "土蜂蜜", "即食燕麦片", "曲奇饼干", "海苔片",
             "卤香豆干", "卤蛋", "爽口榨菜", "果冻布丁", "威化", "麦丽素", "肉松饼", "凤爪",
             "锅巴", "米饼"], ["家庭装", "便携装", "分享装"]),
    "百货": ("GG", 40, (15.0, 120.0), ["个", "套"],
            ["收纳箱", "衣架套装", "纯色毛巾", "加厚浴巾", "保温杯", "玻璃水杯", "陶瓷餐具套装",
             "点断式垃圾袋", "卷纸", "抽纸", "软面抄", "中性笔", "折叠伞", "防滑衣架", "摇柄削皮器",
             "密实袋", "保鲜盒", "砧板", "挂钩", "肥皂盒"], ["基础款", "加大款"]),
    "日化": ("RC", 30, (8.0, 60.0), ["瓶", "支"],
            ["洗发水", "沐浴露", "护手霜", "牙膏", "牙刷", "洗衣皂", "香皂", "洗面奶",
             "湿厕纸", "消毒液", "拖把", "去污粉", "驱蚊液", "防晒霜", "剃须刀"],
            ["经典款", "升级款"]),
}
SUPPLIERS = [  # 编码, 名称, 结算方式（GY012 混沌 A10）
    ("GY001", "常鲜食品有限公司", "月结30"), ("GY002", "百惠日用品集团", "月结30"),
    ("GY003", "洁劲日化科技", "月结60"), ("GY004", "康盈食品供应链", "现结"),
    ("GY005", "广达百货贸易", "月结30"), ("GY006", "优家家居制品", "月结60"),
    ("GY007", "晨露乳业", "现结"), ("GY008", "禾风粮油", "月结30"),
    ("GY009", "丽人日化", "月结60"), ("GY010", "洁美纸品", "月结30"),
    ("GY011", "丰泽零食工贸", "现结"), ("GY012", "恒信洗涤用品", "季结90"),
]
GHOST_PRODUCTS = ["P9001", "P9002"]     # A4
GHOST_SUPPLIER = "SUP-9999"             # A5

SEASON = {1: 0.85, 2: 0.88, 3: 0.98, 4: 1.02, 5: 1.06, 6: 0.97,
          7: 0.94, 8: 0.99, 9: 1.04, 10: 1.12, 11: 1.10, 12: 1.08}

# ---------------------------------------------------------------- 舍入与 SQL 语义工具
def d2(x: float) -> float:
    """float 路径的 HALF_UP（仅用于数据生成期取值，不用于答案计算）。"""
    return float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

# ---- 答案链路专用：全 Decimal（与引擎 staging 的 DECIMAL 精确算术 + round HALF_UP 对齐）----
D0 = Decimal("0")
D1 = Decimal("1")
_C2 = Decimal("0.01")
_C4 = Decimal("0.0001")

def dec(v) -> Decimal:
    """按 CSV 文本语义取 Decimal：pandas to_csv 写 str(float)，引擎 ingest 读同一文本为 DECIMAL，
    故 Decimal(str(float)) 与引擎入参逐位一致（杜绝 float 中间态的半分位边界分歧）。"""
    return Decimal(str(v))

def q2(x: Decimal) -> Decimal:
    """SQL round(x, 2)：DECIMAL 精确值上的 HALF_UP。"""
    return x.quantize(_C2, rounding=ROUND_HALF_UP)

def q4(x: Decimal) -> Decimal:
    return x.quantize(_C4, rounding=ROUND_HALF_UP)

def sumsql(values):
    """SQL sum() 语义（Decimal 精确加法）：跳过 NULL/NaN；全 NULL/空 → NULL。"""
    nn = [v for v in values if v is not None and v == v]
    return sum(nn, D0) if nn else None

def money(values, empty_zero=False):
    """sum 后按金额 round 2（Decimal→float 输出）。empty_zero=True 时空组按 0.0
    （对应派生列 else 0 的语义）。"""
    s = sumsql(values)
    if s is None:
        return 0.0 if empty_zero else None
    return float(q2(s))

def ratio(num, den):
    """nullif 语义：分母 0/缺失 → None。num/den 为 Decimal（或 int）精确除法后再量化。"""
    if num is None or not den:
        return None
    return float(q4(num / den))

def build_products():
    rows = []
    for cat, (prefix, n, (lo, hi), units, bases, specs) in CAT_SPEC.items():
        combos = [f"{b}·{s}" for b in bases for s in specs]
        for i in range(n):
            rows.append(dict(
                商品编码=f"{prefix}{i + 1:03d}",
                商品名称=combos[i % len(combos)],
                品类=cat,
                单位=units[i % len(units)],
                标准成本=d2(rng.uniform(lo, hi)),
            ))
    return pd.DataFrame(rows)

def build_stores():
    return pd.DataFrame([{"门店编码": s[0], "门店名称": s[1], "城市": s[2],
                          "大区": s[3], "开业日期": s[5]} for s in STORES])

def build_suppliers():
    return pd.DataFrame([{"供应商编码": s[0], "供应商名称": s[1], "结算方式": s[2]}
                         for s in SUPPLIERS])

# ---------------------------------------------------------------- 混沌注入配额（SPEC §7.1）
QUOTA = {  # 每类脏行在各月的分配（总和与 SPEC 一致）
    "space":   [2, 2, 2, 2, 2, 2, 2, 2, 3, 2, 2, 2],   # A1 空格门店编码 = 25
    "thou":    [2, 1, 2, 1, 1, 1, 2, 1, 1, 1, 1, 1],   # A2 千分位 = 15
    "nodisc":  [4, 3, 4, 3, 3, 3, 4, 3, 4, 3, 3, 3],   # A3 缺折扣 = 40
    "ghost":   [3, 2, 3, 2, 3, 2, 3, 2, 3, 2, 2, 3],   # A4 幽灵商品 = 30
    "channel": [1] * 12,                                # A6 门店自提 = 12
    "zeroqty": [1, 0, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0],   # A7 数量=0 = 5
}
assert sum(QUOTA["space"]) == 25 and sum(QUOTA["thou"]) == 15
assert sum(QUOTA["nodisc"]) == 40 and sum(QUOTA["ghost"]) == 30
assert sum(QUOTA["channel"]) == 12 and sum(QUOTA["zeroqty"]) == 5

DIRTY_STAT = {}

def take_indices(per_month_rows: dict, quota: list, used: set) -> list:
    """从各月的可用行里按配额抽行（与 used 互斥）。"""
    picked = []
    for mi, k in enumerate(quota):
        avail = [i for i in per_month_rows[mi] if i not in used]
        chosen = [int(x) for x in rng.choice(avail, size=k, replace=False)]
        used.update(chosen)
        picked += chosen
    return picked

# ---------------------------------------------------------------- 生成销售流水
def build_sales(products: pd.DataFrame, stock: dict, deep: bool = False):
    prod_by_code = {r["商品编码"]: r for r in products.to_dict("records")}
    price_base = {code: max(1.99, d2(round(r["标准成本"] * rng.uniform(1.35, 1.75) * 2) / 2) - 0.01)
                  for code, r in prod_by_code.items()}
    disc_choices = [0.0] * 6 + [0.05, 0.1, 0.1, 0.15, 0.2]
    rows = []
    seq_counters: dict = {}
    stock_sorted = {st[0]: sorted(stock[st[0]]) for st in OPERATING}
    for mi, (y, m) in enumerate(MONTHS):
        growth = 1.004 ** (mi + 1)
        ndays = calendar.monthrange(y, m)[1]
        for d in range(1, ndays + 1):
            dt = date(y, m, d)
            wd = 1.22 if dt.weekday() >= 5 else 1.0
            for st in OPERATING:
                lam = 27 * st[4] * SEASON[m] * growth * wd
                n = int(rng.poisson(lam))
                codes = stock_sorted[st[0]]
                for _ in range(n):
                    code = codes[int(rng.integers(0, len(codes)))]   # 只卖本店在册商品
                    qty = int(min(6, 1 + rng.poisson(0.8)))
                    price = d2(price_base[code] * rng.uniform(0.95, 1.05))
                    disc = float(rng.choice(disc_choices))
                    seq = seq_counters.get((st[0], dt), 0) + 1
                    seq_counters[(st[0], dt)] = seq
                    rows.append((
                        f"SO-{dt:%Y%m%d}-{st[0]}-{seq:05d}", f"{dt:%Y-%m-%d}", st[0],
                        code, "门店" if rng.random() < 0.74 else "电商",
                        qty, price, disc,
                    ))
    df = pd.DataFrame(rows, columns=["流水号", "销售日期", "门店编码", "商品编码", "渠道",
                                     "数量", "单价", "折扣率"])
    df["单价"] = df["单价"].astype(object)      # 允许千分位字符串
    df["_mrow"] = [MONTH_KEYS.index(r[1][:7]) for r in rows]
    per_month_rows = {mi: df.index[df["_mrow"] == mi].tolist() for mi in range(len(MONTHS))}

    # ---- 混沌注入（互斥） ----
    used: set = set()
    idx_space = take_indices(per_month_rows, QUOTA["space"], used)
    idx_thou = take_indices(per_month_rows, QUOTA["thou"], used)
    idx_nodisc = take_indices(per_month_rows, QUOTA["nodisc"], used)
    idx_ghost = take_indices(per_month_rows, QUOTA["ghost"], used)
    idx_channel = take_indices(per_month_rows, QUOTA["channel"], used)
    idx_zero = take_indices(per_month_rows, QUOTA["zeroqty"], used)

    for i in idx_space:
        df.at[i, "门店编码"] = f" {df.at[i, '门店编码']} "
    for j, i in enumerate(idx_thou):
        # A2 单价文本化：两种都必然类型转换失败——
        #   真·千分位（金额×1000 的分/元单位混乱，如 "36,250.00"）与 货币符号（如 "￥32.70"）
        v = float(df.at[i, "单价"])
        df.at[i, "单价"] = f"{v * 1000:,.2f}" if j % 3 == 0 else f"￥{v:,.2f}"
    for i in idx_nodisc:
        df.at[i, "折扣率"] = np.nan
    for j, i in enumerate(idx_ghost):
        df.at[i, "商品编码"] = GHOST_PRODUCTS[j % 2]
    for i in idx_channel:
        df.at[i, "渠道"] = "门店自提"
    for i in idx_zero:
        df.at[i, "数量"] = 0

    # ---- 轮4 加深注入（--deep；全部改现有行：yellow-保留或合法通过） ----
    if deep:
        # R4-6(a) ENUM 尾随空格："门店 "→strip 后合法，组归属不变 → 答案零漂移
        idx_sp4 = []
        for mi in range(len(MONTHS)):
            pool = [i for i in per_month_rows[mi]
                    if i not in used and df.at[i, "渠道"] in ("门店", "电商")]
            if pool:
                i = int(pool[int(rng.integers(0, len(pool)))])
                used.add(i)
                idx_sp4.append(i)
        for i in idx_sp4:
            df.at[i, "渠道"] = f" {df.at[i, '渠道']} "
        # R4-6(b) ENUM 繁体变体："門店" → enum yellow、行保留 → 渠道月报新增"門店"组
        idx_tc4 = []
        for mi in range(len(MONTHS)):
            pool = [i for i in per_month_rows[mi]
                    if i not in used and df.at[i, "渠道"] == "门店"]
            i = int(pool[int(rng.integers(0, len(pool)))])
            used.add(i)
            idx_tc4.append(i)
        for i in idx_tc4:
            df.at[i, "渠道"] = "門店"
        # R4-7 折扣率=1.0 边界：range [0,1] 含边界 → 通过、无契约黄灯；收入 0、毛利=−成本
        idx_b14 = []
        for mi, k in enumerate([1, 0, 1, 1, 0, 1, 0, 1, 0, 0, 0, 0]):
            if k == 0:
                continue
            pool = [i for i in per_month_rows[mi] if i not in used]
            i = int(pool[int(rng.integers(0, len(pool)))])
            used.add(i)
            idx_b14.append(i)
        for i in idx_b14:
            df.at[i, "折扣率"] = 1.0
        # R4-8 空字符串渠道：CSV 空字段 → NULL 渠道组承接真实销售额（缺失≠enum 违规，命题裁决）
        idx_ec4 = []
        for mi, k in enumerate([0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0]):
            if k == 0:
                continue
            pool = [i for i in per_month_rows[mi]
                    if i not in used and df.at[i, "渠道"] == "门店"]
            i = int(pool[int(rng.integers(0, len(pool)))])
            used.add(i)
            idx_ec4.append(i)
        for i in idx_ec4:
            df.at[i, "渠道"] = np.nan
        DIRTY_STAT.update({
            "轮4-R4-6a 渠道尾随空格(零漂移)": len(idx_sp4),
            "轮4-R4-6b 渠道繁体變體(門店→新组)": len(idx_tc4),
            "轮4-R4-7 折扣率=1.0边界(毛利=−成本)": len(idx_b14),
            "轮4-R4-8 空字符串渠道(NULL组承接)": len(idx_ec4),
        })

    DIRTY_STAT.update({
        "A1 门店编码首尾空格": len(idx_space),
        "A2 单价文本化(千分位/货币符号)": len(idx_thou),
        "A3 折扣率缺失": len(idx_nodisc),
        "A4 幽灵商品行": len(idx_ghost),
        "A6 渠道越枚举(门店自提)": len(idx_channel),
        "A7 数量=0": len(idx_zero),
    })
    return df

# ---------------------------------------------------------------- 生成采购/退货
def build_purchases(products: pd.DataFrame, stock: dict, sales: pd.DataFrame):
    prod_by_code = {r["商品编码"]: r for r in products.to_dict("records")}
    supplier_of = {r["商品编码"]: SUPPLIERS[int(rng.integers(0, len(SUPPLIERS)))][0]
                   for r in products.to_dict("records")}
    sold_units = sales.assign(月份=sales["销售日期"].str[:7]).groupby(
        ["门店编码", "月份"])["数量"].sum().to_dict()      # 以销定采：采购总量≈销售总量
    rows = []
    for mi, (y, m) in enumerate(MONTHS):
        ym = f"{y}{m:02d}"
        mk = MONTH_KEYS[mi]
        ndays = calendar.monthrange(y, m)[1]
        for st in OPERATING:
            codes = sorted(stock[st[0]])
            target = float(sold_units.get((st[0], mk), 0)) * rng.uniform(1.00, 1.12)
            for k in range(1, 5):                      # 每店每月 4 张采购单
                po_no = f"PO-{ym}-{st[0]}-{k:02d}"
                po_day = int(rng.integers(1, ndays + 1))
                order_target = target / 4 * rng.uniform(0.85, 1.15)
                n_lines = int(rng.integers(12, 23))
                for _ in range(n_lines):
                    code = codes[int(rng.integers(0, len(codes)))]
                    qty = max(1, int(order_target / n_lines * rng.uniform(0.5, 1.5)))
                    price = d2(prod_by_code[code]["标准成本"] * rng.uniform(0.93, 1.06))
                    rows.append((po_no, f"{date(y, m, po_day):%Y-%m-%d}", st[0],
                                 code, supplier_of[code], qty, price))
    df = pd.DataFrame(rows, columns=["采购单号", "采购日期", "门店编码", "商品编码",
                                     "供应商编码", "数量", "采购单价"])
    # 退货（从"干净"行选，避免与幽灵供应商重叠）
    n_ret = int(len(df) * 0.13)
    ret_idx = sorted(int(x) for x in rng.choice(len(df), size=n_ret, replace=False))
    rets = []
    for seq, i in enumerate(ret_idx, start=1):
        r = df.iloc[i]
        y, m = int(r["采购日期"][:4]), int(r["采购日期"][5:7])
        ndays = calendar.monthrange(y, m)[1]
        rets.append((f"RT-{y}{m:02d}-{r['门店编码']}-{seq:05d}",
                     f"{date(y, m, int(rng.integers(1, ndays + 1))):%Y-%m-%d}",
                     r["门店编码"], r["商品编码"], r["供应商编码"],
                     int(rng.integers(1, min(5, int(r["数量"])) + 1)), float(r["采购单价"])))
    ret_df = pd.DataFrame(rets, columns=["退货单号", "退货日期", "门店编码", "商品编码",
                                         "供应商编码", "数量", "退货单价"])
    # A5 幽灵供应商：3 行（退货已选完，天然不重叠）
    idx_ghost_sup = [int(x) for x in rng.choice(len(df), size=3, replace=False)]
    for i in idx_ghost_sup:
        df.at[i, "供应商编码"] = GHOST_SUPPLIER
    DIRTY_STAT["A5 幽灵供应商采购行"] = 3
    return df, ret_df

# ---------------------------------------------------------------- 库存快照（由流水推演）
def build_snapshots(products, stock, sales: pd.DataFrame, purch: pd.DataFrame):
    sold = sales.assign(月份=sales["销售日期"].str[:7]).groupby(
        ["门店编码", "商品编码", "月份"])["数量"].sum().to_dict()
    bought = purch.assign(月份=purch["采购日期"].str[:7]).groupby(
        ["门店编码", "商品编码", "月份"])["数量"].sum().to_dict()
    rows = []
    state = {}
    for mi, (y, m) in enumerate(MONTHS):
        mk = MONTH_KEYS[mi]
        end_day = f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
        for st in OPERATING:
            for p in sorted(stock[st[0]]):
                key = (st[0], p)
                if key not in state:
                    state[key] = int(rng.integers(100, 401))
                delta = int(bought.get((st[0], p, mk), 0)) - int(sold.get((st[0], p, mk), 0))
                state[key] = max(0, state[key] + delta + int(rng.integers(-3, 4)))
                rows.append((mk, end_day, st[0], p, state[key]))
    df = pd.DataFrame(rows, columns=["快照月份", "快照日期", "门店编码", "商品编码", "期末数量"])
    # A8：期末数量 = -10（选一个原值≥30 的行）
    cand = df[(df["期末数量"] >= 30)].index.tolist()
    i = int(cand[int(rng.integers(0, len(cand)))])
    df.at[i, "期末数量"] = -10
    DIRTY_STAT["A8 期末数量=-10"] = 1
    DIRTY_STAT["A8 注入位置"] = f"{df.at[i, '快照月份']} {df.at[i, '门店编码']} {df.at[i, '商品编码']}"
    return df

def build_promotions():
    rows = []
    for st in OPERATING:
        for _ in range(3):
            mi = int(rng.integers(0, 12))
            y, m = MONTHS[mi]
            ndays = calendar.monthrange(y, m)[1]
            sd = date(y, m, int(rng.integers(1, max(2, ndays - 20))))
            ed = min(sd + timedelta(days=int(rng.integers(6, 22))), date(y, m, ndays))
            rows.append((st[0], f"{st[1]} 会员日", f"{sd:%Y-%m-%d}", f"{ed:%Y-%m-%d}",
                         d2(rng.uniform(0.05, 0.30))))
    rows.append(("HD01", "双11 狂欢", "2025-11-05", "2025-11-12", 1.50))   # A9 越界
    rows.append(("HN01", "店庆让利", "2026-03-03", "2026-03-10", 0.90))    # A9 越界
    DIRTY_STAT["A9 促销折扣力度越界"] = 2
    return pd.DataFrame(rows, columns=["门店编码", "活动名称", "开始日期", "结束日期", "折扣力度"])

# ---------------------------------------------------------------- 台账拼接（SPEC §2 规则）
LEDGER_COLS = ["事项类型", "单据号", "单据日期", "门店编码", "商品编码", "供应商编码",
               "渠道", "数量", "单价", "折扣率", "期末数量"]

def build_ledger(sales, purch, rets, snaps):
    seg_sales = pd.DataFrame({
        "事项类型": "销售", "单据号": sales["流水号"], "单据日期": sales["销售日期"],
        "门店编码": sales["门店编码"], "商品编码": sales["商品编码"],
        "供应商编码": "", "渠道": sales["渠道"], "数量": sales["数量"],
        "单价": sales["单价"], "折扣率": sales["折扣率"], "期末数量": np.nan,
    })
    seg_purch = pd.DataFrame({
        "事项类型": "采购", "单据号": purch["采购单号"], "单据日期": purch["采购日期"],
        "门店编码": purch["门店编码"], "商品编码": purch["商品编码"],
        "供应商编码": purch["供应商编码"], "渠道": "", "数量": purch["数量"],
        "单价": purch["采购单价"], "折扣率": np.nan, "期末数量": np.nan,
    })
    seg_ret = pd.DataFrame({
        "事项类型": "采购退货", "单据号": rets["退货单号"], "单据日期": rets["退货日期"],
        "门店编码": rets["门店编码"], "商品编码": rets["商品编码"],
        "供应商编码": rets["供应商编码"], "渠道": "", "数量": rets["数量"],
        "单价": rets["退货单价"], "折扣率": np.nan, "期末数量": np.nan,
    })
    seg_snap = pd.DataFrame({
        "事项类型": "期末库存",
        "单据号": [f"SN-{a}-{b}-{c}" for a, b, c in
                   zip(snaps["快照月份"], snaps["门店编码"], snaps["商品编码"])],
        "单据日期": snaps["快照日期"], "门店编码": snaps["门店编码"],
        "商品编码": snaps["商品编码"], "供应商编码": "", "渠道": "",
        "数量": np.nan, "单价": np.nan, "折扣率": np.nan, "期末数量": snaps["期末数量"],
    })
    return pd.concat([seg_sales, seg_purch, seg_ret, seg_snap], ignore_index=True)[LEDGER_COLS]

# ---------------------------------------------------------------- 密封答案（纯 pandas/Decimal 独立重算）
def truth_sales(sales: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    """契约处理后的销售真相（SPEC §7.1 A1/A2/A3/A4/A6/A7 裁决）。

    全 Decimal 逐行链式：以 CSV 文本语义取值（dec(str(float)) 即引擎 ingest 所见的
    DECIMAL 入参），quantity×unit_price×(1-discount)、quantity×std_cost 等每一步都是
    DECIMAL 精确算术，round(…,2) 用 HALF_UP——与引擎 staging 逐行对齐，
    根除 float64 中间态在半分位边界（x.xx5）与引擎的分歧。
    """
    prod = {r["商品编码"]: (r["品类"], dec(r["标准成本"])) for r in products.to_dict("records")}
    region_of = {s[0]: s[3] for s in STORES}
    recs = []
    for r in sales.itertuples(index=False):
        store = str(r.门店编码).strip()                                     # A1
        channel = None if pd.isna(r.渠道) else str(r.渠道).strip()           # strip_strings 清洗所有字符串列
        qty_d = Decimal(int(r.数量))
        disc_d = D0 if pd.isna(r.折扣率) else dec(float(r.折扣率))           # A3
        price_d = None if isinstance(r.单价, str) else dec(float(r.单价))    # A2 文本化→转换失败
        cat, cost_d = prod.get(r.商品编码, (None, None))                     # A4 幽灵商品
        net_raw = qty_d * price_d * (D1 - disc_d) if price_d is not None else None
        net = q2(net_raw) if net_raw is not None else None
        cost_raw = qty_d * cost_d if cost_d is not None else None
        scost = q2(cost_raw) if cost_raw is not None else None
        gross = q2(net_raw - cost_raw) \
            if (net_raw is not None and cost_raw is not None) else None
        ecomm = (net if channel == "电商" else D0) if net is not None else None
        recs.append(dict(月份=r.销售日期[:7], 门店=store, 大区=region_of[store],
                         商品编码=r.商品编码, 品类=cat, 渠道=channel, 数量=int(r.数量),
                         净额=net, 成本=scost, 毛利=gross, 电商=ecomm))
    return pd.DataFrame(recs)

def answer_reports(ts, purch, rets, snaps, stores: pd.DataFrame):
    name_of = {r["门店编码"]: r["门店名称"] for r in stores.to_dict("records")}
    sup_name = {s[0]: s[1] for s in SUPPLIERS}

    purch = purch.copy()
    purch["供应商"] = purch["供应商编码"].map(sup_name)          # SUP-9999 → None
    purch["采购额"] = [q2(Decimal(int(q)) * dec(p))
                      for q, p in zip(purch["数量"], purch["采购单价"])]
    purch["月份"] = purch["采购日期"].str[:7]
    purch["大区"] = purch["门店编码"].map({s[0]: s[3] for s in STORES})
    rets = rets.copy()
    rets["退货额"] = [q2(Decimal(int(q)) * dec(p))
                      for q, p in zip(rets["数量"], rets["退货单价"])]
    rets["月份"] = rets["退货日期"].str[:7]
    rets["大区"] = rets["门店编码"].map({s[0]: s[3] for s in STORES})
    snaps2 = snaps.copy()
    snaps2["月份"] = snaps2["快照月份"]

    ans = {}

    # 1. monthly_kpi ------------------------------------------------------
    rows = []
    for mk in MONTH_KEYS:
        s = ts[ts["月份"] == mk]
        stock = int(snaps2[snaps2["月份"] == mk]["期末数量"].sum())
        rev = sumsql(s["净额"])
        rows.append({
            "月份": mk, "销售额": money(s["净额"]), "销售成本": money(s["成本"]),
            "毛利": money(s["毛利"]),
            "毛利率": ratio(sumsql(s["毛利"]), rev),
            "期末库存量": stock,
            "库存周转率": ratio(sumsql(s["成本"]), stock),
            "电商销售占比": ratio(sumsql(s["电商"]), rev),
            "动销商品数": int(s["商品编码"].nunique()),
        })
    ans["monthly_kpi"] = {"columns": ["月份", "销售额", "销售成本", "毛利", "毛利率",
                                      "期末库存量", "库存周转率", "电商销售占比", "动销商品数"],
                          "rows": rows}

    # 2. region_month ----------------------------------------------------
    rows = []
    for mk in MONTH_KEYS:
        for rg in ["华东", "华北", "华南"]:
            s = ts[(ts["月份"] == mk) & (ts["大区"] == rg)]
            p = purch[(purch["月份"] == mk) & (purch["大区"] == rg)]["采购额"]
            r = rets[(rets["月份"] == mk) & (rets["大区"] == rg)]["退货额"]
            rev = sumsql(s["净额"])
            pv, rv = sumsql(p), sumsql(r)
            net_pur = q2((pv if pv is not None else D0) - (rv if rv is not None else D0))
            rows.append({"月份": mk, "大区": rg, "销售额": money(s["净额"]),
                         "净采购": float(net_pur),
                         "毛利": money(s["毛利"]),
                         "毛利率": ratio(sumsql(s["毛利"]), rev)})
    ans["region_month"] = {"columns": ["月份", "大区", "销售额", "净采购", "毛利", "毛利率"],
                           "rows": rows}

    # 3. category_month --------------------------------------------------
    cats = sorted({c for c in ts["品类"].dropna().unique()}) + [None]   # GROUP BY 动态取组
    rows = []
    for mk in MONTH_KEYS:
        for c in cats:
            sel = ts["品类"].eq(c) if c is not None else ts["品类"].isna()
            s = ts[(ts["月份"] == mk) & sel]
            rev = sumsql(s["净额"])
            rows.append({"月份": mk, "品类": c, "销售额": money(s["净额"]),
                         "销售数量": int(s["数量"].sum()), "毛利": money(s["毛利"]),
                         "毛利率": ratio(sumsql(s["毛利"]), rev)})
    ans["category_month"] = {"columns": ["月份", "品类", "销售额", "销售数量", "毛利", "毛利率"],
                             "rows": rows}

    # 4. channel_month ---------------------------------------------------
    # 注意：宽表里非销售行（采购/退货/库存）渠道为 NULL，销售额/毛利按 else 0 计 0.0 而非 NULL
    chans = sorted({c for c in ts["渠道"].dropna().unique()}) + [None]  # GROUP BY 动态取组（轮4 含"門店"）
    rows = []
    for mk in MONTH_KEYS:
        for ch in chans:
            sel = ts["渠道"].eq(ch) if ch is not None else ts["渠道"].isna()
            s = ts[(ts["月份"] == mk) & sel]
            if ch is None and len(s) == 0:      # NULL 渠道组只含非销售行 → 指标恒 0/NULL
                rev_sum, gross_sum = 0.0, 0.0
            else:
                rev_sum, gross_sum = sumsql(s["净额"]), sumsql(s["毛利"])
            rows.append({"月份": mk, "渠道": ch, "销售额": money(s["净额"], empty_zero=(ch is None)),
                         "毛利": money(s["毛利"], empty_zero=(ch is None)),
                         "电商销售占比": ratio(sumsql(s["电商"]), rev_sum)})
    ans["channel_month"] = {"columns": ["月份", "渠道", "销售额", "毛利", "电商销售占比"],
                            "rows": rows}

    # 5. store_rank ------------------------------------------------------
    rows = []
    for st in OPERATING:
        s = ts[ts["门店"] == st[0]]
        stock = int(snaps2[snaps2["门店编码"] == st[0]]["期末数量"].sum())
        rev = sumsql(s["净额"])
        rows.append({"门店": name_of[st[0]], "销售额": money(s["净额"]),
                     "毛利": money(s["毛利"]),
                     "毛利率": ratio(sumsql(s["毛利"]), rev),
                     "库存周转率": ratio(sumsql(s["成本"]), stock)})
    ans["store_rank"] = {"columns": ["门店", "销售额", "毛利", "毛利率", "库存周转率"],
                         "rows": rows}

    # 6. supplier_rank ---------------------------------------------------
    psup = purch.groupby(purch["供应商"].fillna("__NULL__"))["采购额"].apply(list).to_dict()
    rsup = rets.groupby(rets["供应商编码"].map(sup_name).fillna("__NULL__"))["退货额"].apply(list).to_dict()
    rows = []
    for k in sorted(set(psup) | set(rsup), key=lambda x: (x == "__NULL__", x)):
        p = sumsql(psup.get(k, []))
        r = sumsql(rsup.get(k, []))
        p = p if p is not None else D0
        r = r if r is not None else D0
        rows.append({"供应商": None if k == "__NULL__" else k,
                     "采购额": float(q2(p)), "退货额": float(q2(r)), "净采购": float(q2(p - r))})
    ans["supplier_rank"] = {"columns": ["供应商", "采购额", "退货额", "净采购"], "rows": rows}

    return ans

def sort_answer(ans):
    """时间升序；同月内维度升序，NULL 最后；无时间报表维度升序、NULL 最后。"""
    dim_of = {"monthly_kpi": None, "region_month": "大区", "category_month": "品类",
              "channel_month": "渠道", "store_rank": "门店", "supplier_rank": "供应商"}
    for key, rep in ans.items():
        dim = dim_of[key]
        rows = rep["rows"]
        if dim is None:
            rows.sort(key=lambda r: r["月份"])
        elif "月份" in rep["columns"]:
            rows.sort(key=lambda r: (r["月份"], r[dim] is None, str(r[dim] or "")))
        else:
            rows.sort(key=lambda r: (r[dim] is None, str(r[dim] or "")))

# ---------------------------------------------------------------- 自检断言
def sanity(sales, purch, rets, snaps, products, stores, ledger, ts):
    assert products["商品编码"].is_unique and stores["门店编码"].is_unique
    assert len(SUPPLIERS) == 12 and GHOST_PRODUCTS[0] not in set(products["商品编码"])
    assert GHOST_SUPPLIER not in {s[0] for s in SUPPLIERS}
    assert sales["流水号"].is_unique
    assert int((purch["供应商编码"] == GHOST_SUPPLIER).sum()) == 3
    assert not any(rets["供应商编码"] == GHOST_SUPPLIER)
    # 每月幽灵商品行 ≥1（品类 NULL 组每月存在）
    ghost_months = set(ts.loc[ts["品类"].isna(), "月份"])
    assert ghost_months == set(MONTH_KEYS), f"幽灵商品未覆盖全年: {ghost_months}"
    # 门店自提每月恰 1 行
    ch = sales[sales["渠道"] == "门店自提"].groupby(sales["销售日期"].str[:7]).size()
    assert len(ch) == 12 and (ch == 1).all(), f"门店自提分布异常: {ch.to_dict()}"
    # 千分位行不得占满任何（月×渠道）组
    for (mk, chn), n in ts[ts["净额"].isna()].groupby(["月份", "渠道"]).size().items():
        valid = ts[(ts["月份"] == mk) & (ts["渠道"] == chn) & ts["净额"].notna()]
        assert len(valid) > 0, f"{mk}×{chn} 千分位占满整组"
    # 覆盖性：每月×大区都有销售；8 城市全命中
    cov = ts.groupby(["月份", "大区"]).size()
    assert len(cov) == 36, f"月×大区覆盖 {len(cov)}"
    assert ts["门店"].map({s[0]: s[2] for s in STORES}).nunique() == 8
    # 毛利率区间
    mg = ts.groupby("月份").apply(lambda g: sumsql(g["毛利"]) / sumsql(g["净额"]),
                                  include_groups=False)
    assert 0.15 <= mg.min() and mg.max() <= 0.45, f"月度毛利率越界: {mg.min():.3f}~{mg.max():.3f}"
    # HB03 零流水
    assert not sales["门店编码"].str.contains("HB03").any()
    # 台账行数守恒
    assert len(ledger) == len(sales) + len(purch) + len(rets) + len(snaps)
    # 库存自洽：以销定采后月末库存应稳定（不单调爆仓/清零）
    ms = snaps.groupby("快照月份")["期末数量"].sum()
    base = ms.iloc[0]
    assert ms.min() > base * 0.4 and ms.max() < base * 2.0, f"库存漂移异常: {ms.to_dict()}"

# ---------------------------------------------------------------- 主流程
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    EXPECTED.mkdir(parents=True, exist_ok=True)

    products = build_products()
    stores = build_stores()
    suppliers = build_suppliers()

    # 门店在册商品（每店 60 个；每商品 ≥2 店在册）
    stock = {}
    for st in OPERATING:
        stock[st[0]] = set(products["商品编码"][rng.choice(len(products), size=60, replace=False)])
    for p in products["商品编码"]:
        while sum(1 for s in OPERATING if p in stock[s[0]]) < 2:
            st = OPERATING[int(rng.integers(0, len(OPERATING)))]
            stock[st[0]].add(p)

    print("=" * 64)
    print("S1 荟品汇零售连锁 · 数据生成（seed =", SEED, "| 轮4加深 =", DEEP, "）")
    print("=" * 64)
    t0 = datetime.now()
    sales = build_sales(products, stock, deep=DEEP)
    purch, rets = build_purchases(products, stock, sales)
    snaps = build_snapshots(products, stock, sales, purch)
    promos = build_promotions()
    ledger = build_ledger(sales, purch, rets, snaps)

    # ---- 自检 ----
    ts = truth_sales(sales, products)
    sanity(sales, purch, rets, snaps, products, stores, ledger, ts)

    # ---- 写 inbox（诱饵文件先写 + 显式压旧 mtime，保证 multi_match 新文件胜出）----
    stale = OUT / "采购单_202606.csv"
    purch[purch["采购日期"] <= "2026-06-30"].to_csv(stale, index=False, encoding="utf-8-sig")
    os.utime(stale, (datetime.now().timestamp() - 30 * 86400,) * 2)

    stores.to_excel(OUT / "门店.xlsx", index=False, engine="xlsxwriter")
    products.to_excel(OUT / "商品.xlsx", index=False, engine="xlsxwriter")
    suppliers.to_excel(OUT / "供应商.xlsx", index=False, engine="xlsxwriter")
    promos.to_excel(OUT / "促销活动.xlsx", index=False, engine="xlsxwriter")
    sales.drop(columns="_mrow").to_csv(OUT / "销售流水_202608.csv", index=False, encoding="utf-8-sig")
    purch.to_csv(OUT / "采购单_202608.csv", index=False, encoding="utf-8-sig")
    os.utime(OUT / "采购单_202608.csv", (datetime.now().timestamp(),) * 2)
    rets.to_csv(OUT / "采购退货_202608.csv", index=False, encoding="utf-8-sig")
    snaps.to_csv(OUT / "库存快照_202608.csv", index=False, encoding="utf-8-sig")
    ledger.to_csv(OUT / "进销存台账_202608.csv", index=False, encoding="utf-8-sig")

    # ---- 密封答案 ----
    ans = answer_reports(ts, purch, rets, snaps, stores)
    sort_answer(ans)
    expect_counts = {"monthly_kpi": 12, "region_month": 36, "category_month": 48,
                     "channel_month": 60 if DEEP else 48, "store_rank": 8, "supplier_rank": 13}
    for k, n in expect_counts.items():
        assert len(ans[k]["rows"]) == n, f"{k} 行数 {len(ans[k]['rows'])} != {n}"
    ans_file = EXPECTED / "answer.json"
    ans_file.write_text(json.dumps(ans, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    digest = hashlib.sha256(ans_file.read_bytes()).hexdigest()
    (EXPECTED / "manifest.sha256").write_text(f"{digest}  answer.json\n", encoding="utf-8", newline="\n")

    # ---- 报告 ----
    print(f"\n[文件] 输出目录 {OUT}")
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name:24s} {f.stat().st_size / 1024:9.1f} KB")
    print(f"\n[规模] 销售流水 {len(sales):,} | 采购 {len(purch):,} | 退货 {len(rets):,} | "
          f"快照 {len(snaps):,} | 台账 {len(ledger):,} | 月份 {MONTH_KEYS[0]}~{MONTH_KEYS[-1]}")
    print("\n[混沌注入统计]")
    for k, v in DIRTY_STAT.items():
        print(f"  {k:30s} {v}")
    print("  A11 采购单双文件(mtime 旧<新)    2")
    print("  A12 销售/库存行空供应商基线      结构性")
    print("  A13 筹备门店 HB03 零流水         1")
    print("\n[答案行数]")
    for k in ["monthly_kpi", "region_month", "category_month", "channel_month",
              "store_rank", "supplier_rank"]:
        print(f"  {k:16s} {len(ans[k]['rows'])} 行")
    print(f"\n[密封] {ans_file}  sha256={digest[:16]}...")
    print(f"耗时 {(datetime.now() - t0).total_seconds():.1f}s → 生成完毕")

if __name__ == "__main__":
    main()
