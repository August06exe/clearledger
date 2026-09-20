# -*- coding: utf-8 -*-
"""集团经营核算·利润阶梯（ladder 账套）演示数据生成器

确定性：无随机、无时间戳，双跑逐字节一致。
场景：集团按"项目×月"台账核算（人力成本/费用由数据集成层预聚合入账——真实做法），
     维表按编码关联；8 项目 × 14 个月，量级轻（跑批秒级）。
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "instances" / "ladder" / "data" / "inbox"

MONTHS = [f"{y}-{m:02d}-01" for y, m in
          [(2025, m) for m in range(7, 13)] + [(2026, m) for m in range(1, 9)]]

PROJECTS = [  # (编码, 名称, 部门, 客户, 行业, 成本中心, 规模系数)
    ("P01", "人力外包-华东制造线", "D1", "C01", "I1", "CC01", 1.30),
    ("P02", "人力外包-金融坐席线", "D1", "C02", "I2", "CC01", 1.10),
    ("P03", "IT 外派-银行核心组",  "D1", "C02", "I2", "CC02", 0.90),
    ("P04", "IT 外派-政务云项目",  "D2", "C03", "I3", "CC02", 0.80),
    ("P05", "灵活用工-连锁零售池", "D2", "C04", "I1", "CC03", 0.70),
    ("P06", "灵活用工-物流旺季池", "D2", "C05", "I1", "CC03", 0.60),
    ("P07", "咨询-薪酬体系设计",   "D3", "C06", "I3", "CC04", 0.40),
    ("P08", "咨询-组织变革陪跑",   "D3", "C01", "I2", "CC04", 0.30),
]
DEPTS = [("D1", "交付中心"), ("D2", "销售与客户成功中心"), ("D3", "专业服务中心")]
CUSTOMERS = [("C01", "华辰制造集团"), ("C02", "恒信银行"), ("C03", "市政务云"),
             ("C04", "千惠连锁"), ("C05", "迅达物流"), ("C06", "启元咨询")]
INDUSTRIES = [("I1", "制造与物流"), ("I2", "金融"), ("I3", "政企与咨询")]
COST_CENTERS = [("CC01", "交付一部"), ("CC02", "交付二部"), ("CC03", "用工运营部"), ("CC04", "咨询业务部")]
GROUP_PARAMS = [("G", "明账集团（演示）", "7.10")]
POLICIES = [("ST1", "稳岗补贴", "补贴类"), ("ST2", "研发费用加计", "税收类")]


def _amt(base: float, scale: float, i: int, salt: int) -> str:
    """确定性"伪波动"：月份序号与盐值做模运算，避免随机数。"""
    wobble = ((i * 37 + salt * 13) % 23 - 11) / 100.0      # -0.11 ~ +0.11
    trend = 1 + i * 0.008                                   # 温和增长
    v = base * scale * trend * (1 + wobble)
    return f"{round(v, 2)}"


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> int:
    INBOX.mkdir(parents=True, exist_ok=True)

    # 1) 项目月度台账（main fact：项目×月，人力成本/费用由集成层预聚合入账）
    rows = []
    for pcode, pname, dept, cust, ind, cc, scale in PROJECTS:
        for i, month in enumerate(MONTHS):
            hc = 520000 * scale                            # 人力成本基数
            rows.append([
                month, pcode,
                _amt(760000, scale, i, 1), _amt(56000, scale, i, 2), _amt(9000, scale, i, 3),
                _amt(hc * 0.78, 1, i, 4), _amt(hc * 0.19, 1, i, 5), _amt(hc * 0.03, 1, i, 6),
                _amt(14000, scale, i, 7), _amt(11000, scale, i, 8),
                _amt(6500, scale, i, 9), _amt(2200, scale, i, 10), _amt(18000, scale, i, 11),
                cust, ind, cc, ("ST1" if (i % 3) == 0 else "ST2") if scale >= 0.6 else "ST2",
                "G",
            ])
    write_csv(INBOX / "项目月度台账_202608.csv", [
        "期间", "项目编码", "收入额", "摊销收入", "政府补助",
        "工资奖金", "社保公积金", "招聘费", "商旅费", "费用报销", "平台管理费", "残保金",
        "集团费用分摊", "客户编码", "行业编码", "成本中心编码", "政策编码", "集团键"], rows)

    # 2) 维表
    write_csv(INBOX / "项目主数据_202608.csv", ["项目编码", "项目名称", "一级部门编码", "项目经理"],
              [[p[0], p[1], p[2], f"经理-{p[0]}"] for p in PROJECTS])
    write_csv(INBOX / "组织架构_集团_202608.csv", ["一级部门编码", "一级部门"], [list(d) for d in DEPTS])
    write_csv(INBOX / "客户主数据_202608.csv", ["客户编码", "客户名称"], [list(c) for c in CUSTOMERS])
    write_csv(INBOX / "行业字典_202608.csv", ["行业编码", "行业"], [list(i) for i in INDUSTRIES])
    write_csv(INBOX / "成本中心_202608.csv", ["成本中心编码", "成本中心"], [list(c) for c in COST_CENTERS])
    write_csv(INBOX / "集团参数_202608.csv", ["集团键", "集团名称", "预算汇率"], [list(g) for g in GROUP_PARAMS])
    write_csv(INBOX / "补助政策_202608.csv", ["政策编码", "政策名称", "补助类型"], [list(p) for p in POLICIES])

    print(f"[ladder] 台账 {len(rows)} 行（{len(PROJECTS)} 项目 × {len(MONTHS)} 月）+ 7 张维表 → {INBOX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
