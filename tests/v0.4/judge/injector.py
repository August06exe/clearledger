# -*- coding: utf-8 -*-
"""混沌注入器（测试 Agent 专用）：对 _c_retail / _c_hro 副本 inbox 施加注入。
调用前由 bash 先把 inbox 恢复为备份态。不改基线实例、不改引擎。"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def retail_inbox() -> Path:
    return ROOT / "instances/_c_retail/data/inbox"


def hro_inbox() -> Path:
    return ROOT / "instances/_c_hro/data/inbox"


def dup_xlsx_row(path: Path, key_col: int, new_vals: dict[int, str], key_hint: str):
    """复制 key_col 列值==key_hint 的首行，追加为新行，并按 new_vals 覆写列。
    key_hint 若是表头名则按名定位，否则视为键值。"""
    import openpyxl
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    header = [str(c.value).strip() for c in ws[1]]
    ki = header.index(key_hint) if key_hint in header else key_col
    src_row = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if str(row[ki]).strip() == str(key_hint):
            src_row = list(row)
            break
    assert src_row is not None, f"{path.name} 找不到键 {key_hint}"
    new = list(src_row)
    for idx, val in new_vals.items():
        new[idx] = val
    ws.append(new)
    wb.save(path)
    return src_row, new


def R1():  # 门店.xlsx 复制 HD01 一行，改门店名称（同键不同名）
    p = retail_inbox() / "门店.xlsx"
    src, new = dup_xlsx_row(p, 0, {1: "HD01 幽灵二店（混沌注入）"}, "HD01")
    print(f"R1 注入：复制 {src} → 追加 {new}")


def R2():  # 销售流水 2 行改相同流水号
    p = retail_inbox() / "销售流水_202608.csv"
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    dup = rows[1][0]  # 第 2 数据行流水号改为与第 1 数据行相同
    rows[2][0] = dup
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    print(f"R2 注入：第1/第2数据行流水号同为 {dup}")


def R3():  # 商品.xlsx 表头 品类→类别
    import openpyxl
    p = retail_inbox() / "商品.xlsx"
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    header = [c.value for c in ws[1]]
    i = header.index("品类")
    ws.cell(row=1, column=i + 1).value = "类别"
    wb.save(p)
    print("R3 注入：商品.xlsx 表头 品类→类别")


def R4():  # 库存快照清成仅表头
    p = retail_inbox() / "库存快照_202608.csv"
    with open(p, encoding="utf-8-sig") as f:
        header = f.readline()
    with open(p, "w", encoding="utf-8-sig") as f:
        f.write(header)
    print(f"R4 注入：库存快照_202608.csv 清成仅表头（{len(header)} 字节）")


def R5a():  # 删除 销售流水_202608.csv
    (retail_inbox() / "销售流水_202608.csv").unlink()
    print("R5a 注入：删除 销售流水_202608.csv")


def R5b():  # 改名 两 pattern 全不命中
    p = retail_inbox() / "销售流水_202608.csv"
    p.rename(retail_inbox() / "销售明细202608_最终版.csv")
    print("R5b 注入：改名 销售明细202608_最终版.csv")


def R9():  # 追加 450 行文本化单价（千分位/货币符号两种格式，均保证真文本化）
    p = retail_inbox() / "销售流水_202608.csv"
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    header, sample = rows[0], rows[1]
    i = {name: k for k, name in enumerate(header)}
    with open(p, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for k in range(450):
            row = list(sample)
            row[i["流水号"]] = f"R9CHAOS{k:06d}"
            row[i["销售日期"]] = "2026-08-15"
            price = round(1000 + (k * 13 % 900) + 0.55, 2)  # ≥1000 保证千分位含逗号
            row[i["单价"]] = f"{price:,.2f}" if k % 2 == 0 else f"￥{price:.2f}"
            w.writerow(row)
    print(f"R9 注入：追加 450 行文本化单价（原数据行 {len(rows) - 1}）")


def R10():  # 旧采购单 touch 成最新
    import os
    p = retail_inbox() / "采购单_202606.csv"
    new = retail_inbox() / "采购单_202608.csv"
    os.utime(p, (new.stat().st_mtime + 100,) * 2)
    print(f"R10 注入：touch 采购单_202606.csv（mtime 现晚于 202608）")


# ---------------- hro ----------------

def H1():  # 交付组.xlsx 复制 GR-F01 一行
    p = hro_inbox() / "交付组.xlsx"
    import openpyxl
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    header = [c.value for c in ws[1]]
    ki = header.index("组编码")
    src = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if str(row[ki]).strip() == "GR-F01":
            src = list(row)
            break
    assert src, "GR-F01 未找到"
    ws.append(src)
    wb.save(p)
    print(f"H1 注入：复制 GR-F01 行 {src}（同键复制）")


def H2():  # 合同.xlsx 2 行改相同合同号
    p = hro_inbox() / "合同.xlsx"
    import openpyxl
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    header = [c.value for c in ws[1]]
    ki = header.index("合同号")
    it = ws.iter_rows(min_row=2)
    r1 = next(it)
    r2 = next(it)
    v = r1[ki].value
    ws.cell(row=r2[0].row, column=ki + 1).value = v
    wb.save(p)
    print(f"H2 注入：第1/第2份合同号同为 {v}")


def H3():  # 客户.xlsx 表头 行业→所属行业
    import openpyxl
    p = hro_inbox() / "客户.xlsx"
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    header = [c.value for c in ws[1]]
    i = header.index("行业")
    ws.cell(row=1, column=i + 1).value = "所属行业"
    wb.save(p)
    print("H3 注入：客户.xlsx 表头 行业→所属行业")


def H4():  # 事业部.xlsx 清空（仅表头）
    import openpyxl
    p = hro_inbox() / "事业部.xlsx"
    wb = openpyxl.load_workbook(p)
    ws = wb.active
    ws.delete_rows(2, ws.max_row)
    wb.save(p)
    print("H4 注入：事业部.xlsx 清成 0 数据行")


def H5a():  # 删除 月度账单_202608.csv
    (hro_inbox() / "月度账单_202608.csv").unlink()
    print("H5a 注入：删除 月度账单_202608.csv")


def H5b():  # 改名 账单final0808.csv（两 pattern 全不命中）
    p = hro_inbox() / "月度账单_202608.csv"
    p.rename(hro_inbox() / "账单final0808.csv")
    print("H5b 注入：改名 账单final0808.csv")


def H8():  # 月度账单追加 4 行千分位
    p = hro_inbox() / "月度账单_202608.csv"
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    header, sample = rows[0], rows[1]
    i = {name: k for k, name in enumerate(header)}
    with open(p, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for k in range(4):
            row = list(sample)
            row[i["月份"]] = "2026-08-01"
            row[i["合同号"]] = sample[i["合同号"]]
            row[i["账单金额"]] = f"{50000 + k * 111:,.2f}"
            w.writerow(row)
    print(f"H8 注入：追加 4 行千分位账单（原数据行 {len(rows) - 1}）")


if __name__ == "__main__":
    case = sys.argv[1]
    globals()[case]()
