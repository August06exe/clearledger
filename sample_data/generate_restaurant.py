# -*- coding: utf-8 -*-
"""实例二演示数据：连锁餐饮（与销售公司完全不同的数据形态）

  orders.csv   订单流水（订单×菜品行，含渠道：堂食/外卖/小程序）
  dishes.xlsx  菜品主数据（类别/标准成本）
  stores.xlsx  门店主数据（城市/商圈）

用法：.venv/Scripts/python sample_data/generate_restaurant.py [输出目录]
默认输出 instances/restaurant/data/inbox/
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(7)

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path(__file__).resolve().parents[1] / "instances" / "restaurant" / "data" / "inbox"
OUT.mkdir(parents=True, exist_ok=True)

START = date(2025, 10, 1)
END = date.today() - timedelta(days=1)

STORES = [
    ("S01", "万象城店", "上海", "购物中心", 1.6), ("S02", "静安寺店", "上海", "交通枢纽", 1.3),
    ("S03", "张江店", "上海", "社区", 0.9), ("S04", "国贸店", "北京", "购物中心", 1.5),
    ("S05", "望京店", "北京", "社区", 1.0), ("S06", "天河城店", "广州", "购物中心", 1.4),
    ("S07", "科韵路店", "广州", "景区", 0.8), ("S08", "春熙路店", "成都", "购物中心", 1.2),
]
CHANNELS = [("堂食", 0.52), ("外卖", 0.36), ("小程序", 0.12)]
CATEGORIES = {
    "热菜": [("招牌红烧肉", 68, 26), ("水煮鱼片", 78, 31), ("宫保鸡丁", 48, 17), ("麻婆豆腐", 32, 9),
             ("糖醋排骨", 58, 22), ("干煸四季豆", 36, 11), ("鱼香茄子", 34, 10)],
    "凉菜": [("口水鸡", 38, 12), ("拍黄瓜", 16, 4), ("凉拌木耳", 18, 5), ("皮蛋豆腐", 20, 6)],
    "主食": [("担担面", 28, 8), ("扬州炒饭", 32, 9), ("白米饭", 3, 1), ("酸辣粉", 26, 7)],
    "饮品": [("鲜榨橙汁", 25, 7), ("酸梅汤", 12, 3), ("可乐", 8, 3), ("柠檬茶", 18, 5)],
    "甜点": [("杨枝甘露", 28, 9), ("红豆双皮奶", 22, 7), ("芒果班戟", 30, 11)],
}
CAT_PREFIX = {"热菜": "H", "凉菜": "C", "主食": "M", "饮品": "D", "甜点": "P"}
CAT_WEIGHT = {"热菜": 0.42, "凉菜": 0.16, "主食": 0.22, "饮品": 0.13, "甜点": 0.07}
HOUR_W = {11: 1.0, 12: 2.6, 13: 1.8, 14: 0.6, 16: 0.4, 17: 1.2, 18: 2.2, 19: 2.4, 20: 1.4, 21: 0.6}
SEASON = {1: 0.85, 2: 0.9, 3: 1.0, 4: 1.02, 5: 1.05, 6: 0.98, 7: 0.95, 8: 1.0, 9: 1.05, 10: 1.15, 11: 1.1, 12: 1.05}


def build_dishes() -> pd.DataFrame:
    rows, pid = [], 1
    for cat, items in CATEGORIES.items():
        for name, price, cost in items:
            rows.append(dict(菜品编码=f"{CAT_PREFIX[cat]}{pid:03d}", 菜品名称=name, 菜品类别=cat,
                             标准成本=float(cost)))
            pid += 1
    return pd.DataFrame(rows)


def build_stores() -> pd.DataFrame:
    return pd.DataFrame([(s[0], s[1], s[2], s[3]) for s in STORES],
                        columns=["门店编码", "门店名称", "城市", "商圈类型"])


def build_orders(dishes: pd.DataFrame) -> pd.DataFrame:
    d_p = np.array([CAT_WEIGHT[c] for c in dishes["菜品类别"]])
    d_p = d_p / d_p.sum()
    d_recs = dishes.to_dict("records")
    ch_names = [c[0] for c in CHANNELS]
    ch_p = np.array([c[1] for c in CHANNELS])

    rows = []
    d = START
    while d <= END:
        month_t = (d.year - 2025) * 12 + (d.month - 10)
        weekday_f = 1.25 if d.weekday() >= 5 else 1.0
        for st in STORES:
            base = 46 * (1.01 ** month_t) * st[4] * SEASON[d.month] * weekday_f
            for _ in range(int(rng.poisson(base))):
                hour = int(rng.choice(list(HOUR_W), p=np.array(list(HOUR_W.values())) / sum(HOUR_W.values())))
                channel = str(rng.choice(ch_names, p=ch_p))
                n_lines = int(rng.choice([1, 2, 3, 4, 5], p=[.25, .35, .22, .12, .06]))
                order_no = f"RO-{d:%Y%m%d}-{len(rows) + 1:07d}"
                for _ in range(n_lines):
                    dish = d_recs[int(rng.choice(len(d_recs), p=d_p))]
                    qty = int(1 + rng.poisson(0.6))
                    price = round(dish["标准成本"] * (2.2 + rng.random() * 0.9), 0)
                    rows.append((order_no, f"{d:%Y-%m-%d} {hour:02d}:{int(rng.integers(0, 60)):02d}",
                                 st[0], dish["菜品编码"], qty, float(price), round(qty * price, 2), channel))
        d += timedelta(days=1)
    return pd.DataFrame(rows, columns=["订单号", "下单时间", "门店编码", "菜品编码",
                                       "数量", "单价", "金额", "渠道"])


def main() -> None:
    dishes = build_dishes()
    stores = build_stores()
    orders = build_orders(dishes)

    orders.to_csv(OUT / "orders.csv", index=False, encoding="utf-8-sig")
    dishes.to_excel(OUT / "dishes.xlsx", index=False, engine="xlsxwriter")
    stores.to_excel(OUT / "stores.xlsx", index=False, engine="xlsxwriter")

    m = orders["下单时间"].str[:7]
    print("=" * 56)
    for f in sorted(OUT.iterdir()):
        print(f"  {f.name:22s} {f.stat().st_size / 1024:8.1f} KB")
    print("=" * 56)
    print(f"订单流水行数: {len(orders):,} | 订单数: {orders['订单号'].nunique():,}")
    print(f"覆盖月份: {m.min()} ~ {m.max()}（{m.nunique()} 个月）")
    print(f"渠道分布: {orders['渠道'].value_counts().to_dict()}")
    print("生成完毕 →", OUT)


if __name__ == "__main__":
    main()
