# -*- coding: utf-8 -*-
"""S2 睿才人力：数据生成器 + 混沌注入 + 密封标准答案（命题方出品）

产出：
  1. instances/hro/data/inbox/  下 8 个源文件 + 1 个诱饵文件（混沌 H11）
  2. tests/v0.4/S2_hro/expected/answer.json       （六张报表密封答案）
  3. tests/v0.4/S2_hro/expected/manifest.sha256   （answer.json 的 SHA256）

确定性：固定 seed，重复运行逐字节复现。
答案独立于引擎：纯 pandas/Decimal 按 SPEC §7.1 契约裁决模拟"契约处理后的真相"再聚合。
维度语义提示：事业部/客户/行业/级别/交付组是 join 来的标签列（幽灵合同行 → NULL 组）；
合同维度是主流水原始列（幽灵合同 HT-9999/HT-8888 是真实键值，各自成组，不落 NULL）。
用法：.venv/Scripts/python.exe tests/v0.4/S2_hro/generate.py [输出目录]
"""
from __future__ import annotations

import calendar  # noqa: F401  (保留与 S1 生成器同构的导入面)
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260919
rng = np.random.default_rng(SEED)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
_ARGS = sys.argv[1:]
DEEP = "--deep" in _ARGS                     # 轮4 加深口径：注入加深混沌并重密封答案
_POS = [a for a in _ARGS if not a.startswith("--")]
OUT = Path(_POS[0]) if _POS else ROOT / "instances" / "hro" / "data" / "inbox"
EXPECTED = HERE / "expected"

MONTHS = [(y, m) for y in (2025, 2026) for m in range(1, 13)
          if (y == 2025 and m >= 9) or (y == 2026 and m <= 8)]
MONTH_KEYS = [f"{y}-{m:02d}" for y, m in MONTHS]
FIRST_DAY = {mk: f"{mk}-01" for mk in MONTH_KEYS}

# ---------------------------------------------------------------- 主数据（SPEC §1，硬编码）
BUS = [("BU-FIN", "金融事业部", "沈国峰"),
       ("BU-NET", "互联网事业部", "陆佳炜"),
       ("BU-MFG", "制造业交付事业部", "韩志强")]
GROUPS = [("GR-F01", "金融一组", "BU-FIN"), ("GR-F02", "金融二组", "BU-FIN"),
          ("GR-N01", "互联网一组", "BU-NET"), ("GR-N02", "互联网二组", "BU-NET"),
          ("GR-M01", "制造一组", "BU-MFG"), ("GR-M02", "制造二组", "BU-MFG")]
INDUSTRY = {"金融": "BU-FIN", "互联网": "BU-NET", "制造": "BU-MFG",
            "零售": "BU-MFG", "文体": "BU-MFG"}          # 行业 → 签约事业部
CUSTOMERS = [  # 编码, 名称, 行业, 级别（H8 文体=越枚举；H9 恒信数创级别改 S级=越枚举）
    ("CUST-01", "汇金证券股份有限公司", "金融", "A"),
    ("CUST-02", "泰和人寿保险有限公司", "金融", "A"),
    ("CUST-03", "银信消费金融", "金融", "B"),
    ("CUST-04", "九州银行股份公司", "金融", "A"),
    ("CUST-05", "中融融资租赁", "金融", "B"),
    ("CUST-06", "安诚基金管理", "金融", "B"),
    ("CUST-07", "普惠小贷", "金融", "C"),
    ("CUST-08", "灵犀互娱网络科技", "互联网", "A"),
    ("CUST-09", "橙了么电商", "互联网", "A"),
    ("CUST-10", "云梯智联", "互联网", "B"),
    ("CUST-11", "恒信数创", "互联网", "S级"),          # H9 越枚举
    ("CUST-12", "风行视频", "互联网", "B"),
    ("CUST-13", "蓝鲸出行", "互联网", "C"),
    ("CUST-14", "极客软件园", "互联网", "C"),
    ("CUST-15", "重工机械集团", "制造", "A"),
    ("CUST-16", "精密器件制造", "制造", "B"),
    ("CUST-17", "新能源汽车部件", "制造", "B"),
    ("CUST-18", "家电装配厂", "制造", "C"),
    ("CUST-19", "纺织印染联合", "制造", "B"),
    ("CUST-20", "精密光学仪器", "制造", "C"),
    ("CUST-21", "万家连锁超市", "零售", "B"),
    ("CUST-22", "优选百货", "零售", "C"),
    ("CUST-23", "鲜花电商", "零售", "C"),
    ("CUST-24", "大剧院文化发展", "文体", "C"),        # H8 行业越枚举
]
POSITIONS = [  # 岗位, 成本下限, 成本上限, 权重
    ("项目经理", 13500, 16500, 0.05), ("软件开发工程师", 8800, 11800, 0.22),
    ("测试工程师", 6200, 8800, 0.18), ("运维工程师", 5800, 8200, 0.15),
    ("客户服务专员", 4400, 6200, 0.22), ("数据处理专员", 3900, 5400, 0.18),
]
BASE_HEADCOUNT = {"金融": (280, 360), "互联网": (320, 440), "制造": (190, 280),
                  "零售": (140, 210), "文体": (90, 140)}
GROUP_SUFFIX = {"金融": ["GR-F01", "GR-F02"], "互联网": ["GR-N01", "GR-N02"],
                "制造": ["GR-M01", "GR-M02"], "零售": ["GR-M01", "GR-M02"],
                "文体": ["GR-M01", "GR-M02"]}
SURNAMES = list("王李张刘陈杨黄赵周吴徐孙马朱胡郭何林罗郑梁谢宋唐许韩冯邓曹彭")
GIVEN = list("伟敏芳静磊洋艳勇杰娟涛明超霞平刚桂华健斌莉志强子轩雨桐一诺浩然欣怡沐宸")
GHOST_CONTRACT_ROSTER = "HT-9999"     # H3
GHOST_CONTRACT_PAY = "HT-8888"        # H4

# ---------------------------------------------------------------- 舍入与聚合工具
def d2(x: float) -> float:
    return float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def d4(x: float) -> float:
    return float(Decimal(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

def ratio(num, den):
    """nullif 语义：分母 0/缺失 → None。"""
    if num is None or not den:
        return None
    return d4(num / den)

def fsum(values) -> float:
    return math.fsum(v for v in values if v is not None and v == v)

DIRTY_STAT = {}

# ---------------------------------------------------------------- 生成合同（40 份）
def make_contract(seq, customer, start, end, tag):
    code, name, industry, level = customer
    bu_code, bu_name, _ = next(b for b in BUS if b[0] == INDUSTRY[industry])
    return dict(合同号=f"HT-{seq:04d}", 客户编码=code,
                签约事业部编码=bu_code, 签约事业部名称=bu_name,
                月服务费=0.0,       # 定价在花名册生成后回填（按人均成本上浮，SPEC §1.3）
                开始月=start, 结束月=end, 行业=industry, 级别=level, tag=tag)

def build_contracts():
    rows = []
    # 每客户 1 份基础合同（全部全窗口）→ 24 份
    for i, c in enumerate(CUSTOMERS):
        rows.append(make_contract(i + 1, c, "2025-09", "2026-08", "base"))
    # 追加 14 份：6 份提前截止（前 4 份被 H1 选中超止月开票）、2 份期中起租（H2 提前开票）、6 份全窗口
    early_ends = ["2026-01", "2026-01", "2026-02", "2026-03", "2026-03", "2026-04"]
    mid_starts = ["2026-01", "2026-03"]
    for i in range(14):
        c = CUSTOMERS[int(rng.integers(0, len(CUSTOMERS)))]
        if i < 6:
            rows.append(make_contract(25 + i, c, "2025-09", early_ends[i], "early"))
        elif i < 8:
            rows.append(make_contract(25 + i, c, mid_starts[i - 6], "2026-08", "mid"))
        else:
            rows.append(make_contract(25 + i, c, "2025-09", "2026-08", "full"))
    # 2 份未来合同（H12：零台账活动）
    rows.append(make_contract(1001, CUSTOMERS[int(rng.integers(0, len(CUSTOMERS)))],
                              "2026-10", "2027-09", "future"))
    rows.append(make_contract(1002, CUSTOMERS[int(rng.integers(0, len(CUSTOMERS)))],
                              "2026-11", "2027-10", "future"))
    return pd.DataFrame(rows)

# ---------------------------------------------------------------- 生成花名册（员工×月份）
def build_roster(contracts: pd.DataFrame):
    emp_next = [10000]
    positions = [p[0] for p in POSITIONS]
    pw = np.array([p[3] for p in POSITIONS])
    pw = pw / pw.sum()

    def new_employee(industry):
        emp_next[0] += 1
        pos = str(rng.choice(positions, p=pw))
        lo, hi = next((p[1], p[2]) for p in POSITIONS if p[0] == pos)
        return dict(员工编号=f"EMP{emp_next[0]}",
                    姓名=str(rng.choice(SURNAMES)) + str(rng.choice(GIVEN)),
                    交付组编码=str(rng.choice(GROUP_SUFFIX[industry])), 岗位=pos,
                    月薪资成本=d2(rng.uniform(lo, hi)))

    staff: dict = {}        # ht → list[employee]
    hc_hist: dict = {}      # ht → {mk: headcount}
    rows = []
    for mi, mk in enumerate(MONTH_KEYS):
        growth = 1 + 0.006 * mi
        for c in contracts.to_dict("records"):
            if c["tag"] == "future":
                continue
            if not (c["开始月"] <= mk <= c["结束月"]):
                continue
            ht = c["合同号"]
            lo, hi = BASE_HEADCOUNT[c["行业"]]
            target = int(rng.uniform(lo, hi) * growth * rng.uniform(0.96, 1.04))
            cur = staff.setdefault(ht, [])
            if len(cur) < target:
                cur.extend(new_employee(c["行业"]) for _ in range(target - len(cur)))
            elif len(cur) > target:
                drop = set(int(x) for x in rng.choice(len(cur), size=len(cur) - target, replace=False))
                staff[ht] = [e for j, e in enumerate(cur) if j not in drop]
                cur = staff[ht]
            hc_hist.setdefault(ht, {})[mk] = len(cur)
            for e in cur:
                rows.append((e["员工编号"], e["姓名"], FIRST_DAY[mk], e["交付组编码"],
                             ht, e["岗位"], e["月薪资成本"]))
    df = pd.DataFrame(rows, columns=["员工编号", "姓名", "月份", "交付组编码", "合同号",
                                     "岗位", "月薪资成本"])
    return df, hc_hist, staff

def price_contracts(contracts: pd.DataFrame, staff: dict):
    """合同定价：初期在册人均月薪资成本 × U(1.12, 1.28)，rounded 到十元（SPEC §1.3）。
    未来合同给名义值 9500（零台账活动，费用不进任何答案，且不触发 range 黄灯噪音）。"""
    fee = {}
    for c in contracts.to_dict("records"):
        if c["tag"] == "future":
            fee[c["合同号"]] = 9500.0
            continue
        cur = staff[c["合同号"]]
        sample = cur[: min(60, len(cur))]
        avg = fsum(e["月薪资成本"] for e in sample) / max(1, len(sample))
        fee[c["合同号"]] = float((Decimal(avg * rng.uniform(1.12, 1.28)) / 10
                                  ).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 10)
    return fee

# ---------------------------------------------------------------- 账单与回款
def build_bills(contracts, hc_hist, fee):
    rows = []
    normal = [c for c in contracts.to_dict("records") if c["tag"] != "future"]
    h1_pick = [c for c in normal if c["tag"] == "early"][:4]        # H1：4 份超止月
    h1_months = {}
    for c in h1_pick:
        ei = MONTH_KEYS.index(c["结束月"])
        h1_months[c["合同号"]] = [MONTH_KEYS[ei + 1], MONTH_KEYS[ei + 2]]
    h2_months = {c["合同号"]: [MONTH_KEYS[MONTH_KEYS.index(c["开始月"]) - 1]]
                 for c in normal if c["tag"] == "mid"}              # H2：2 份提前起月
    for c in normal:
        ht = c["合同号"]
        for mk in MONTH_KEYS:
            if c["开始月"] <= mk <= c["结束月"]:
                rows.append(dict(月份=FIRST_DAY[mk], 合同号=ht,
                                 账单金额=d2(hc_hist[ht][mk] * fee[ht]), tag="normal"))
        for mk in h1_months.get(ht, []):
            last_active = [x for x in MONTH_KEYS if c["开始月"] <= x <= c["结束月"]]
            rows.append(dict(月份=FIRST_DAY[mk], 合同号=ht,
                             账单金额=d2(hc_hist[ht][last_active[-1]] * fee[ht]), tag="H1"))
        for mk in h2_months.get(ht, []):
            rows.append(dict(月份=FIRST_DAY[mk], 合同号=ht,
                             账单金额=d2(int(rng.integers(50, 91)) * fee[ht]), tag="H2"))
    df = pd.DataFrame(rows)
    df["账单金额"] = df["账单金额"].astype(object)     # 允许千分位字符串（H5）
    # H5 千分位：6 个不同月份各 1 行
    picked5: set = set()
    for mk in MONTH_KEYS:
        pool = [i for i in df.index[(df["月份"] == FIRST_DAY[mk]) & (df["tag"] == "normal")
                                    & (df["账单金额"] >= 10000)] if i not in picked5]
        if pool:
            picked5.add(int(pool[int(rng.integers(0, len(pool)))]))
        if len(picked5) >= 6:
            break
    for i in picked5:
        df.at[i, "账单金额"] = f"{float(df.at[i, '账单金额']):,.2f}"
        df.at[i, "tag"] = "H5"
    DIRTY_STAT["H5 账单千分位"] = len(picked5)
    # H6 空格合同号：8 个不同月份各 1 行（避开 H5 行）
    picked6: set = set()
    for mk in MONTH_KEYS:
        pool = [i for i in df.index[(df["月份"] == FIRST_DAY[mk]) & (df["tag"] == "normal")]
                if i not in picked5 | picked6]
        if pool:
            picked6.add(int(pool[int(rng.integers(0, len(pool)))]))
        if len(picked6) >= 8:
            break
    for i in picked6:
        df.at[i, "合同号"] = f" {df.at[i, '合同号']} "
    DIRTY_STAT["H6 账单合同号首尾空格"] = len(picked6)
    return df

def build_payments(bills: pd.DataFrame):
    rows = []
    for i, r in bills.iterrows():
        if r["tag"] == "H5":
            continue                         # 千分位账单无对应回款（SPEC §1.5）
        if rng.random() < 0.87:
            rows.append(dict(月份=r["月份"], 合同号=r["合同号"],
                             回款金额=d2(float(r["账单金额"]) * rng.uniform(0.90, 1.00))))
    pay = pd.DataFrame(rows)
    # H10：负回款（冲销）1 行
    i = int(rng.integers(0, len(pay)))
    DIRTY_STAT["H10 负回款-500 位置"] = f"{pay.at[i, '月份']} {pay.at[i, '合同号']}"
    pay.at[i, "回款金额"] = -500.00
    # H4：幽灵合同回款 2 行
    ghost = pd.DataFrame([
        dict(月份=FIRST_DAY["2025-12"], 合同号=GHOST_CONTRACT_PAY, 回款金额=120000.00),
        dict(月份=FIRST_DAY["2026-04"], 合同号=GHOST_CONTRACT_PAY, 回款金额=80000.00),
    ])
    DIRTY_STAT["H4 幽灵合同回款(HT-8888)"] = 2
    return pd.concat([pay, ghost], ignore_index=True)

# ---------------------------------------------------------------- 台账拼接（SPEC §2 规则）
LEDGER_COLS = ["事项类型", "单据号", "单据月份", "合同号", "交付组编码", "员工编号",
               "姓名", "岗位", "月薪资成本", "金额"]

def build_ledger(bills, pays, roster):
    seg_bill = pd.DataFrame({
        "事项类型": "账单",
        "单据号": [f"BL-{mk}-{ht.strip()}" for mk, ht in zip(bills["月份"].str[:7], bills["合同号"])],
        "单据月份": bills["月份"], "合同号": bills["合同号"],
        "交付组编码": "", "员工编号": "", "姓名": "", "岗位": "",
        "月薪资成本": np.nan, "金额": bills["账单金额"],
    })
    seg_pay = pd.DataFrame({
        "事项类型": "回款",
        "单据号": [f"PY-{mk}-{ht.strip()}" for mk, ht in zip(pays["月份"].str[:7], pays["合同号"])],
        "单据月份": pays["月份"], "合同号": pays["合同号"],
        "交付组编码": "", "员工编号": "", "姓名": "", "岗位": "",
        "月薪资成本": np.nan, "金额": pays["回款金额"],
    })
    seg_roster = pd.DataFrame({
        "事项类型": "在册",
        "单据号": [f"RS-{mk}-{e}" for mk, e in zip(roster["月份"].str[:7], roster["员工编号"])],
        "单据月份": roster["月份"], "合同号": roster["合同号"],
        "交付组编码": roster["交付组编码"], "员工编号": roster["员工编号"],
        "姓名": roster["姓名"], "岗位": roster["岗位"],
        "月薪资成本": roster["月薪资成本"], "金额": np.nan,
    })
    return pd.concat([seg_bill, seg_pay, seg_roster], ignore_index=True)[LEDGER_COLS]

# ---------------------------------------------------------------- 密封答案（纯 pandas 独立重算）
def truth(contracts, bills, pays, roster, industry_override=None):
    """契约处理后的真相（SPEC §7.1 H1~H7 裁决）。

    每行统一携带全部维度键与全部派生列（数值恒定，NULL 以 None 表示、参与比率时按 0 处理）：
    维度键 = 月份/合同/客户/行业/级别/事业部/交付组（join 标签列对幽灵合同为 None）
    派生列 = 收入/回款/成本/毛利额（对应 wide 派生 bill_amt/pay_amt/cost_amt/gross_amt）
    """
    crec = {}
    cname = {c[0]: c[1] for c in CUSTOMERS}
    cind = {c[0]: c[2] for c in CUSTOMERS}
    if industry_override:
        cind.update(industry_override)      # 轮4 深度注入的行业变体（建模 客户.xlsx join 结果）
    clv = {c[0]: c[3] for c in CUSTOMERS}
    for c in contracts.to_dict("records"):
        crec[c["合同号"]] = dict(customer=c["客户编码"], bu=c["签约事业部名称"],
                                 industry=cind[c["客户编码"]], level=clv[c["客户编码"]])
    gname = {g[0]: g[1] for g in GROUPS}

    def base(ht_raw):
        ht = str(ht_raw).strip()                       # H6
        c = crec.get(ht)                               # H3/H4 幽灵 → None
        return dict(月份=None, 合同=ht,
                    客户=cname[c["customer"]] if c else None,
                    行业=c["industry"] if c else None,
                    级别=c["level"] if c else None,
                    事业部=c["bu"] if c else None,
                    交付组=None, 员工=None,
                    收入=0.0, 回款=0.0, 成本=0.0, 毛利额=0.0)

    rows = []
    for r in bills.itertuples(index=False):
        d = base(r.合同号)
        d["月份"] = r.月份[:7]
        try:
            amt = float(r.账单金额)   # 合法 decimal 文本（轮4 H4-5 "…​.0"）解析成功；￥/千分位文本 → H5 裁决 0
        except (TypeError, ValueError):
            amt = 0.0
        d["收入"], d["毛利额"] = amt, amt
        rows.append(d)
    for r in pays.itertuples(index=False):
        d = base(r.合同号)
        d["月份"] = r.月份[:7]
        d["回款"] = float(r.回款金额)                                     # H10 负数保留
        rows.append(d)
    for r in roster.itertuples(index=False):
        d = base(r.合同号)
        d["月份"] = r.月份[:7]
        d["交付组"] = gname[r.交付组编码]
        d["员工"] = r.员工编号
        cost = 0.0 if pd.isna(r.月薪资成本) else float(r.月薪资成本)       # H7a 缺省 0
        d["成本"], d["毛利额"] = cost, -cost
        rows.append(d)
    return pd.DataFrame(rows)

def build_answer(t: pd.DataFrame):
    BU_NAMES = [b[1] for b in BUS]
    GROUP_NAMES = [g[1] for g in GROUPS]
    INDUSTRIES = sorted({i for i in t.loc[t["行业"].notna(), "行业"]}) + [None]  # GROUP BY 动态取组（轮4 含"金融业"）
    DIMSETS = [["月份"], ["月份", "事业部"], ["月份", "行业"], ["事业部"], ["行业"],
               ["交付组"], ["客户"], ["合同"]]

    A: dict = {}

    def norm(v):
        """dict 键归一化：pandas 把 None 升格为 NaN，统一折回 None。"""
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else v

    def key_of(dims, values):
        """键按维度集命名空间化——不同维度集的一元键（如两个 None 组）不得互相污染。"""
        return (tuple(dims), tuple(norm(v) for v in values))

    def add(d):
        for dims in DIMSETS:
            k = key_of(dims, [d[x] for x in dims])
            slot = A.setdefault(k, dict(收入=0.0, 回款=0.0, 成本=0.0, 毛利额=0.0,
                                        员工=set(), 合同=set()))
            slot["收入"] += d["收入"]
            slot["回款"] += d["回款"]
            slot["成本"] += d["成本"]
            slot["毛利额"] += d["毛利额"]
            emp = norm(d.get("员工"))
            if emp:
                slot["员工"].add(emp)
            if d["_是账单"]:
                slot["合同"].add(d["合同"])        # 在单合同数：账单行即计（不看金额）

    for r in t.to_dict("records"):
        r["_是账单"] = r["_tag"] == "账单"
        add(r)

    def m(dims, values):
        slot = A.get(key_of(dims, values),
                     dict(收入=0.0, 回款=0.0, 成本=0.0, 毛利额=0.0, 员工=set(), 合同=set()))
        rev, pay, cost, gross = slot["收入"], slot["回款"], slot["成本"], slot["毛利额"]
        hc = len(slot["员工"])
        return dict(rev=d2(rev), pay=d2(pay), cost=d2(cost), gross=d2(gross),
                    hc=hc, contracts=len(slot["合同"]),
                    毛利率=ratio(gross, rev), 回款率=ratio(pay, rev),
                    人均=d2(rev / hc) if hc else None)

    ans = {}
    rows = []
    for mk in MONTH_KEYS:
        x = m(["月份"], [mk])
        rows.append({"月份": mk, "服务费收入": x["rev"], "人力成本": x["cost"],
                     "毛利": x["gross"], "毛利率": x["毛利率"], "回款额": x["pay"],
                     "回款率": x["回款率"], "外派人数": x["hc"], "人均产值": x["人均"],
                     "在单客户数": int(t[(t["月份"] == mk) & (t["_tag"] == "账单")]["客户"].nunique())})
    ans["monthly_kpi"] = {"columns": ["月份", "服务费收入", "人力成本", "毛利", "毛利率",
                                      "回款额", "回款率", "外派人数", "人均产值", "在单客户数"],
                          "rows": rows}

    rows = []
    for mk in MONTH_KEYS:
        for bu in BU_NAMES + [None]:
            if key_of(["月份", "事业部"], [mk, bu]) not in A:   # GROUP BY 语义：只产出存在的组
                continue
            x = m(["月份", "事业部"], [mk, bu])
            rows.append({"月份": mk, "事业部": bu, "服务费收入": x["rev"],
                         "毛利": x["gross"], "毛利率": x["毛利率"], "外派人数": x["hc"]})
    ans["bu_month"] = {"columns": ["月份", "事业部", "服务费收入", "毛利", "毛利率", "外派人数"],
                       "rows": rows}

    rows = []
    for g in GROUP_NAMES + [None]:
        x = m(["交付组"], [g])
        rows.append({"交付组": g, "外派人数": x["hc"], "人力成本": x["cost"],
                     "人均人力成本": d2(x["cost"] / x["hc"]) if x["hc"] else None})
    ans["group_rank"] = {"columns": ["交付组", "外派人数", "人力成本", "人均人力成本"],
                         "rows": rows}

    rows = []
    for c in sorted(set(t.loc[t["客户"].notna(), "客户"])) + [None]:
        x = m(["客户"], [c])
        rows.append({"客户": c, "服务费收入": x["rev"], "回款额": x["pay"],
                     "应收余额": d2(x["rev"] - x["pay"]), "在单合同数": x["contracts"]})
    ans["customer_ar"] = {"columns": ["客户", "服务费收入", "回款额", "应收余额", "在单合同数"],
                          "rows": rows}

    rows = []
    for mk in MONTH_KEYS:
        for ind in INDUSTRIES:
            if key_of(["月份", "行业"], [mk, ind]) not in A:    # GROUP BY 语义：只产出存在的组
                continue
            x = m(["月份", "行业"], [mk, ind])
            rows.append({"月份": mk, "行业": ind, "服务费收入": x["rev"],
                         "毛利": x["gross"], "外派人数": x["hc"]})
    ans["industry_month"] = {"columns": ["月份", "行业", "服务费收入", "毛利", "外派人数"],
                             "rows": rows}

    rows = []
    for ht in sorted(set(t["合同"])):                  # 幽灵合同是真实键值，各自成组
        x = m(["合同"], [ht])
        rows.append({"合同": ht, "服务费收入": x["rev"], "回款额": x["pay"],
                     "应收余额": d2(x["rev"] - x["pay"]), "外派人数": x["hc"]})
    ans["contract_ledger"] = {"columns": ["合同", "服务费收入", "回款额", "应收余额", "外派人数"],
                              "rows": rows}
    return ans

def sort_answer(ans):
    dim_of = {"monthly_kpi": None, "bu_month": "事业部", "group_rank": "交付组",
              "customer_ar": "客户", "industry_month": "行业", "contract_ledger": "合同"}
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
def sanity(contracts, bills, pays, roster, ledger, t):
    assert contracts["合同号"].is_unique and len(contracts) == 40
    assert GHOST_CONTRACT_ROSTER not in set(contracts["合同号"])
    assert GHOST_CONTRACT_PAY not in set(contracts["合同号"])
    assert len(roster) >= 100_000, f"花名册 {len(roster)} < 10 万"
    assert len(ledger) == len(bills) + len(pays) + len(roster)
    # 每月每事业部有账单（覆盖性）
    cov = t[(t["_tag"] == "账单") & t["事业部"].notna()].groupby(["月份", "事业部"]).size()
    assert len(cov) == 36, f"月×事业部覆盖 {len(cov)}"
    inds = set(t[(t["_tag"] == "账单") & t["行业"].notna()]["行业"])
    assert inds >= {"金融", "互联网", "制造", "零售", "文体"}, f"行业覆盖 {inds}"
    # NULL 事业部组月份 = 幽灵在册 ∪ 幽灵回款
    null_bu = set(t[t["事业部"].isna()]["月份"])
    assert null_bu == {"2025-10", "2025-12", "2026-02", "2026-04", "2026-05", "2026-07"}, \
        f"NULL 组月份 {sorted(null_bu)}"
    # 全司毛利率 / 回款率区间
    rev = fsum(t["收入"])
    margin = (rev - fsum(t["成本"])) / rev
    payrate = fsum(t["回款"]) / rev
    assert 0.08 <= margin <= 0.32, f"毛利率越界 {margin:.3f}"
    assert 0.70 <= payrate <= 0.95, f"回款率越界 {payrate:.3f}"
    # 幽灵在册员工恰 5 人
    assert t[t["合同"] == GHOST_CONTRACT_ROSTER]["员工"].nunique() == 5

# ---------------------------------------------------------------- 主流程
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    EXPECTED.mkdir(parents=True, exist_ok=True)

    bu_df = pd.DataFrame(BUS, columns=["事业部编码", "事业部名称", "事业部负责人"])
    group_df = pd.DataFrame(GROUPS, columns=["组编码", "组名称", "所属事业部编码"])
    cust_df = pd.DataFrame(CUSTOMERS, columns=["客户编码", "客户名称", "行业", "客户级别"])

    print("=" * 64)
    print("S2 睿才人力 · 数据生成（seed =", SEED, "| 轮4加深 =", DEEP, "）")
    print("=" * 64)
    t0 = datetime.now()

    contracts = build_contracts()
    roster, hc_hist, staff = build_roster(contracts)
    fees = price_contracts(contracts, staff)
    bills = build_bills(contracts, hc_hist, fees)
    contracts["月服务费"] = [fees[ht] for ht in contracts["合同号"]]
    pays = build_payments(bills)

    # ---- 轮4 加深注入（--deep） ----
    industry_override = None
    if DEEP:
        # H4-6(a) ENUM 尾随空格："金融 " → strip 后合法，组归属不变 → 答案零漂移（改 客户.xlsx）
        cust_df.loc[cust_df["客户编码"] == "CUST-03", "行业"] = "金融 "
        industry_override = {"CUST-03": "金融"}
        # H4-6(b) ENUM 变体："金融业" → enum yellow、行保留 → 行业月报新增"金融业"组（改 客户.xlsx）
        cust_df.loc[cust_df["客户编码"] == "CUST-07", "行业"] = "金融业"
        industry_override["CUST-07"] = "金融业"
        # H4-7 月服务费下界 1000.00：range [1000,100000] 含边界 → 通过、无黄灯；费率不进任何派生 → 零漂移
        contracts.loc[contracts["合同号"] == "HT-0001", "月服务费"] = 1000.0
        # H4-5 账单金额小数文本 "…​.0"：合法 decimal 文本 → 必然解析成功、金额同值 → 零漂移
        idx05 = []
        for mk in MONTH_KEYS:
            pool = [i for i in bills.index[(bills["月份"] == FIRST_DAY[mk]) & (bills["tag"] == "normal")]
                    if i not in idx05]
            if pool and len(idx05) < 3:
                idx05.append(int(pool[int(rng.integers(0, len(pool)))]))
        for i in idx05:
            bills.at[i, "账单金额"] = f"{float(bills.at[i, '账单金额']):.1f}"
        # H4-8 required 空合同号：2 行回款合同号清空 → 设计 §4.2 "required 过滤"，行不进宽表
        cand = [int(i) for i in pays.index[(pays["合同号"] != GHOST_CONTRACT_PAY) & (pays["回款金额"] > 0)]]
        cand = [cand[j] for j in rng.permutation(len(cand))]
        idx_h8, seen_mk = [], set()
        for i in cand:
            mk = pays.at[i, "月份"]
            if mk in seen_mk:
                continue
            idx_h8.append(i)
            seen_mk.add(mk)
            if len(idx_h8) == 2:
                break
        DIRTY_STAT["轮4-H4-6a 行业尾随空格(零漂移)"] = 1
        DIRTY_STAT["轮4-H4-6b 行业ENUM變體(金融业→新组)"] = 1
        DIRTY_STAT["轮4-H4-7 月服务费下界1000(零漂移)"] = 1
        DIRTY_STAT["轮4-H4-5 账单金额小数文本(零漂移)"] = len(idx05)
        DIRTY_STAT["轮4-H4-8 回款空合同号(required过滤)"] = len(idx_h8)
        pays_out = pays.copy()
        pays_out.loc[idx_h8, "合同号"] = ""            # inbox 展示脏值（CSV 空字段）
        pays = pays.drop(idx_h8).reset_index(drop=True)  # 引擎 required 过滤后不进宽表
    else:
        pays_out = pays
    industry_override = industry_override or {}

    # H3 幽灵在册：专属员工 EMP99001~99005，5 个指定月份（交付组为真实组，合同匹空）
    ghost_months = ["2025-10", "2025-12", "2026-02", "2026-05", "2026-07"]
    ghost_rows = []
    for j, mk in enumerate(ghost_months):
        ghost_rows.append((f"EMP9900{j + 1}", "外派员" + chr(65 + j), FIRST_DAY[mk],
                           GROUP_SUFFIX["金融"][j % 2], GHOST_CONTRACT_ROSTER,
                           "客户服务专员", d2(6000 + j * 500)))
    roster = pd.concat([roster, pd.DataFrame(ghost_rows, columns=roster.columns)],
                       ignore_index=True)
    DIRTY_STAT["H3 花名册幽灵合同(HT-9999)"] = len(ghost_rows)
    DIRTY_STAT["H3 月份"] = ",".join(ghost_months)
    # H7a/H7b：月薪资成本缺失 30 行、岗位缺失 12 行（与幽灵行互斥——幽灵行在尾部，从前段抽）
    body = roster.index[:len(roster) - len(ghost_rows)].tolist()
    idx7a = [int(x) for x in rng.choice(body, size=30, replace=False)]
    idx7b = [int(x) for x in rng.choice([i for i in body if i not in idx7a], size=12, replace=False)]
    for i in idx7a:
        roster.at[i, "月薪资成本"] = np.nan
    for i in idx7b:
        roster.at[i, "岗位"] = np.nan
    DIRTY_STAT["H7a 月薪资成本缺失"] = len(idx7a)
    DIRTY_STAT["H7b 岗位缺失"] = len(idx7b)

    ledger = build_ledger(bills, pays, roster)
    DIRTY_STAT["H1 超止月账单"] = int((bills["tag"] == "H1").sum())
    DIRTY_STAT["H2 提前起月账单"] = int((bills["tag"] == "H2").sum())
    DIRTY_STAT["H12 未来合同零活动"] = 2
    DIRTY_STAT["H13 账单/回款行空交付组基线"] = "结构性"

    # ---- 自检 ----
    t = truth(contracts, bills, pays, roster, industry_override=industry_override)
    t["_tag"] = ["账单"] * len(bills) + ["回款"] * len(pays) + ["在册"] * len(roster)
    sanity(contracts, bills, pays, roster, ledger, t)

    # ---- 写 inbox（诱饵先写 + 压旧 mtime）----
    stale = OUT / "回款记录_202607.csv"
    pays_out[pays_out["月份"] <= "2026-07-01"].to_csv(stale, index=False, encoding="utf-8-sig")
    os.utime(stale, (datetime.now().timestamp() - 30 * 86400,) * 2)

    bu_df.to_excel(OUT / "事业部.xlsx", index=False, engine="xlsxwriter")
    group_df.to_excel(OUT / "交付组.xlsx", index=False, engine="xlsxwriter")
    cust_df.to_excel(OUT / "客户.xlsx", index=False, engine="xlsxwriter")
    contracts[["合同号", "客户编码", "签约事业部编码", "签约事业部名称", "月服务费",
               "开始月", "结束月"]].to_excel(OUT / "合同.xlsx", index=False, engine="xlsxwriter")
    roster.to_excel(OUT / "外派花名册_202608.xlsx", index=False, engine="xlsxwriter")
    bills[["月份", "合同号", "账单金额"]].to_csv(OUT / "月度账单_202608.csv",
                                                index=False, encoding="utf-8-sig")
    pays_out.to_csv(OUT / "回款记录_202608.csv", index=False, encoding="utf-8-sig")
    os.utime(OUT / "回款记录_202608.csv", (datetime.now().timestamp(),) * 2)
    ledger.to_csv(OUT / "经营台账_202608.csv", index=False, encoding="utf-8-sig")

    # ---- 密封答案 ----
    ans = build_answer(t)
    sort_answer(ans)
    expect_counts = {"monthly_kpi": 12, "bu_month": 42, "group_rank": 7,
                     "customer_ar": 25,
                     "industry_month": 78 if DEEP else 66, "contract_ledger": 40}
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
    print(f"\n[规模] 花名册 {len(roster):,} | 账单 {len(bills):,} | 回款 {len(pays):,} | "
          f"台账 {len(ledger):,} | 合同 {len(contracts)} | 客户 {len(cust_df)} | "
          f"月份 {MONTH_KEYS[0]}~{MONTH_KEYS[-1]}")
    print("\n[混沌注入统计]")
    for k, v in DIRTY_STAT.items():
        print(f"  {k:34s} {v}")
    print("  H11 回款双文件(mtime 旧<新)        2")
    print("\n[答案行数]")
    for k in ["monthly_kpi", "bu_month", "group_rank", "customer_ar",
              "industry_month", "contract_ledger"]:
        print(f"  {k:16s} {len(ans[k]['rows'])} 行")
    print(f"\n[密封] {ans_file}  sha256={digest[:16]}...")
    print(f"耗时 {(datetime.now() - t0).total_seconds():.1f}s → 生成完毕")

if __name__ == "__main__":
    main()
