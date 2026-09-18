# -*- coding: utf-8 -*-
"""§2 行为断言核对：读 actual_*.json，按 TESTPLAN §2.1/§2.2 逐条断言。
输出 PASS / FAIL / DEVIATE（现象不符 TESTPLAN 文字，底层粒度另证）。
只读 actual 与实例库（只读），不读 expected/。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

results: list[dict] = []


def record(case: str, expect: str, actual: str, verdict: str, evidence: str = ""):
    results.append({"case": case, "expect": expect, "actual": actual,
                    "verdict": verdict, "evidence": evidence})
    print(f"[{verdict:8s}] {case}\n           预期: {expect}\n           实际: {actual}"
          + (f"\n           证据: {evidence}" if evidence else ""))


def load(inst: str, key: str):
    d = json.loads((HERE / f"actual_{inst}.json").read_text(encoding="utf-8"))[key]
    return d["columns"], d["rows"]


def is_null(v):
    return v is None


def main():
    # ---------------- retail ----------------
    cols, rows = load("retail", "monthly_kpi")
    ok = len(rows) == 12 and [r["月份"] for r in rows] == sorted(r["月份"] for r in rows)
    nonnull = all(r["库存周转率"] is not None and r["毛利率"] is not None for r in rows)
    record("retail.monthly_kpi 行数/升序", "12 行、按月升序",
           f"{len(rows)} 行，升序={ok and [r['月份'] for r in rows] == sorted(r['月份'] for r in rows)}",
           "PASS" if ok else "FAIL")
    record("retail.monthly_kpi 非空", "每月库存周转率/毛利率非空",
           f"全非空={nonnull}", "PASS" if nonnull else "FAIL")

    cols, rows = load("retail", "region_month")
    pairs = {(r["月份"], r["大区"]) for r in rows}
    regions = sorted({r["大区"] for r in rows if r["大区"] is not None})
    months = sorted({r["月份"] for r in rows})
    full = len(pairs) == len(months) * len(regions)
    record("retail.region_month 行数", "36 行（3 大区×12 月）",
           f"{len(rows)} 行；distinct(月份,大区)={len(pairs)}，大区数={len(regions)}，月数={len(months)}",
           "PASS" if len(rows) == 36 else "DEVIATE",
           f"引擎 GROUP BY 含筛选维度 城市 → 行分裂；底层(月份,大区)粒度={len(pairs)}，"
           f"网格完整={full}，大区={regions}，大区无空值={all(r['大区'] is not None for r in rows)}")

    cols, rows = load("retail", "category_month")
    pairs = {(r["月份"], r["品类"]) for r in rows}
    null_rows = [r for r in rows if r["品类"] is None]
    null_months = sorted({r["月份"] for r in null_rows})
    null_ok = (len(null_months) == 12 and all(r["销售额"] > 0 for r in null_rows)
               and all(r["毛利"] is None for r in null_rows))
    record("retail.category_month 行数", "48 行",
           f"{len(rows)} 行；distinct(月份,品类)={len(pairs)}",
           "PASS" if len(rows) == 48 else "DEVIATE",
           f"引擎 GROUP BY 含筛选维度 大区 → 行分裂；底层(月份,品类)粒度={len(pairs)}")
    record("retail.category_month NULL 品类组", "品类=null 组只在 12 个月全出现；销售额>0、毛利=null",
           f"null 行 {len(null_rows)} 个（月份×大区），覆盖 {len(null_months)}/12 月；"
           f"全部销售额>0={all(r['销售额'] > 0 for r in null_rows)}，全部毛利=null={all(r['毛利'] is None for r in null_rows)}",
           "PASS" if null_ok else "FAIL", f"null 组月份={null_months}")

    cols, rows = load("retail", "channel_month")
    ch = {r["渠道"]: r for r in rows}
    self_rows = [r for r in rows if r["渠道"] == "门店自提"]
    n_rows = [r for r in rows if r["渠道"] is None]
    ok_self = bool(self_rows) and all(r["销售额"] > 0 for r in self_rows)
    ok_null = bool(n_rows) and all(r["销售额"] == 0.0 and r["电商销售占比"] is None for r in n_rows)
    record("retail.channel_month 行数", "48 行", f"{len(rows)} 行",
           "PASS" if len(rows) == 48 else "FAIL")
    record("retail.channel_month 门店自提组", "存在且销售额>0",
           f"{len(self_rows)} 行，销售额>0={ok_self}", "PASS" if ok_self else "FAIL")
    record("retail.channel_month NULL 渠道组", "销售额=0.0 且电商销售占比=null",
           f"{len(n_rows)} 行，断言={ok_null}", "PASS" if ok_null else "FAIL")

    cols, rows = load("retail", "store_rank")
    has_prep = any("筹备" in (r["门店"] or "") for r in rows)
    record("retail.store_rank", "8 行；不含'北京朝阳店（筹备）'",
           f"{len(rows)} 行；含筹备店={has_prep}；门店={sorted(r['门店'] for r in rows)}",
           "PASS" if len(rows) == 8 and not has_prep else "FAIL")

    cols, rows = load("retail", "supplier_rank")
    n = [r for r in rows if r["供应商"] is None]
    ok_n = len(n) == 1 and n[0]["采购额"] > 0
    record("retail.supplier_rank", "13 行；供应商=null 组采购额>0",
           f"{len(rows)} 行；null 组采购额={n[0]['采购额'] if n else '无'}",
           "PASS" if len(rows) == 13 and ok_n else "FAIL")

    # ---------------- hro ----------------
    cols, rows = load("hro", "monthly_kpi")
    asc = [r["月份"] for r in rows] == sorted(r["月份"] for r in rows)
    nonnull = all(r["毛利率"] is not None and r["回款率"] is not None for r in rows)
    record("hro.monthly_kpi", "12 行、升序；毛利率/回款率非空",
           f"{len(rows)} 行，升序={asc}，全非空={nonnull}",
           "PASS" if len(rows) == 12 and asc and nonnull else "FAIL")

    cols, rows = load("hro", "bu_month")
    pairs = {(r["月份"], r["事业部"]) for r in rows}
    n_rows = [r for r in rows if r["事业部"] is None]
    n_months = sorted({r["月份"] for r in n_rows})
    n_ok = (len(n_rows) == len(n_months) and all(r["服务费收入"] == 0.0 for r in n_rows)
            and all(r["毛利率"] is None for r in n_rows))
    record("hro.bu_month 行数", "42 行（3×12 + NULL 6）",
           f"{len(rows)} 行；distinct(月份,事业部)={len(pairs)}",
           "PASS" if len(rows) == 42 else "DEVIATE",
           f"引擎 GROUP BY 含筛选维度 行业 → 行分裂；底层(月份,事业部)粒度={len(pairs)}")
    record("hro.bu_month NULL 事业部组", "只出现在 SPEC §6 指定 6 个月；服务费收入=0.0、毛利率=null",
           f"覆盖 {len(n_months)} 个月={n_months}；收入全 0.0={all(r['服务费收入'] == 0.0 for r in n_rows)}，"
           f"毛利率全 null={all(r['毛利率'] is None for r in n_rows)}",
           "PASS" if n_months == ["2025-10-01", "2025-12-01", "2026-02-01", "2026-04-01", "2026-05-01", "2026-07-01"] and n_ok
           else ("DEVIATE" if n_ok else "FAIL"))

    cols, rows = load("hro", "group_rank")
    n = [r for r in rows if r["交付组"] is None]
    ok_n = (len(n) >= 1 and all(r["人力成本"] == 0.0 and r["人均人力成本"] is None
                                and r["外派人数"] == 0 for r in n))
    record("hro.group_rank 行数", "7 行（6 交付组 + NULL）",
           f"{len(rows)} 行；distinct 交付组={len({r['交付组'] for r in rows})}",
           "PASS" if len(rows) == 7 else "DEVIATE",
           f"引擎 GROUP BY 含筛选维度 事业部（bu_name 来自合同 join）→ 组名×签约BU 拆分；"
           f"交付组取值={sorted(str(r['交付组']) for r in rows)}")
    record("hro.group_rank NULL 交付组行", "人力成本=0.0、人均人力成本=null、外派人数=0",
           f"null 行 {len(n)} 个，断言={ok_n}", "PASS" if ok_n else "FAIL",
           f"null 行明细={n}")

    cols, rows = load("hro", "customer_ar")
    n = [r for r in rows if r["客户"] is None]
    ok_n = len(n) >= 1 and all(r["回款额"] > 0 and r["应收余额"] < 0 for r in n)
    record("hro.customer_ar", "25 行；客户=null 行回款额>0 且应收余额<0",
           f"{len(rows)} 行；null 行={n}", "PASS" if len(rows) == 25 and ok_n else "FAIL")

    cols, rows = load("hro", "industry_month")
    pairs = {(r["月份"], r["行业"]) for r in rows}
    wt = [r for r in rows if r["行业"] == "文体"]
    wt_months = sorted({r["月份"] for r in wt})
    n_rows = [r for r in rows if r["行业"] is None]
    n_months = sorted({r["月份"] for r in n_rows})
    record("hro.industry_month 行数", "66 行（5 行业×12 + NULL 6）",
           f"{len(rows)} 行；distinct(月份,行业)={len(pairs)}",
           "PASS" if len(rows) == 66 else "DEVIATE",
           f"引擎 GROUP BY 含筛选维度 客户级别 → 行分裂；底层(月份,行业)粒度={len(pairs)}")
    record("hro.industry_month 文体组", "12 个月都有、服务费收入>0",
           f"覆盖 {len(wt_months)}/12 月，收入>0={all(r['服务费收入'] > 0 for r in wt)}",
           "PASS" if len(wt_months) == 12 and all(r["服务费收入"] > 0 for r in wt) else "FAIL")
    record("hro.industry_month NULL 行业组", "只在 6 个指定月份",
           f"覆盖 {len(n_months)} 个月={n_months}",
           "PASS" if n_months == ["2025-10-01", "2025-12-01", "2026-02-01", "2026-04-01", "2026-05-01", "2026-07-01"]
           else "DEVIATE")

    cols, rows = load("hro", "contract_ledger")
    keys = {r["合同"] for r in rows}
    con = duckdb.connect(str(ROOT / "data/warehouse/hro.duckdb"), read_only=True)
    fut = [r[0] for r in con.execute(
        "select contract_no from raw.contracts where start_month >= '2026-10' order by 1").fetchall()]
    con.close()
    h9999 = next((r for r in rows if r["合同"] == "HT-9999"), None)
    h8888 = next((r for r in rows if r["合同"] == "HT-8888"), None)
    ok9999 = h9999 and h9999["外派人数"] == 5
    ok8888 = h8888 and h8888["回款额"] > 0 and h8888["应收余额"] < 0
    no_fut = not (set(fut) & keys)
    record("hro.contract_ledger 行数", "40 行", f"{len(rows)} 行",
           "PASS" if len(rows) == 40 else "FAIL")
    record("hro.contract_ledger 未来合同缺席", f"不含 {fut}（起月≥2026-10）",
           f"缺席={no_fut}", "PASS" if no_fut else "FAIL")
    record("hro.contract_ledger HT-9999", "在榜且外派人数=5",
           f"行={h9999}", "PASS" if ok9999 else "FAIL")
    record("hro.contract_ledger HT-8888", "在榜且回款>0、应收<0",
           f"行={h8888}", "PASS" if ok8888 else "FAIL")

    (HERE / "behavior_checks.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    n_pass = sum(1 for r in results if r["verdict"] == "PASS")
    print(f"\n== 合计 {len(results)} 条：PASS {n_pass} / DEVIATE "
          f"{sum(1 for r in results if r['verdict'] == 'DEVIATE')} / FAIL "
          f"{sum(1 for r in results if r['verdict'] == 'FAIL')} ==")


if __name__ == "__main__":
    main()
