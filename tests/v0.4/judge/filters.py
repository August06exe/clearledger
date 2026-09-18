# -*- coding: utf-8 -*-
"""filter 行为测试（P-6a-d / P-7a-d / R8 / H7 / R11）：黑盒调 run_report/build_query，
记录实际行为 vs TESTPLAN 预期类别。不读 expected/。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from semantic.loader import load_instance  # noqa: E402
from semantic.query import build_query, filter_options, run_report  # noqa: E402

results: list[dict] = []


def record(case: str, expect: str, actual: str, verdict: str, evidence: str = ""):
    results.append({"case": case, "expect": expect, "actual": actual,
                    "verdict": verdict, "evidence": evidence})
    print(f"[{verdict:8s}] {case}\n           预期: {expect}\n           实际: {actual}"
          + (f"\n           证据: {evidence}" if evidence else ""))


def run(inst, key, filters):
    try:
        rows = run_report(inst, key, filters=filters, limit=500)
        return {"ok": True, "rows": rows}
    except Exception as e:
        return {"ok": False, "err": f"{type(e).__name__}: {e}"}


INJ = "华东' OR 1=1--"


def main():
    # ---- P-6a retail region_month 城市=上海 ----
    r = run("retail", "region_month", {"城市": "上海"})
    rows = r["rows"]
    ok = (all(x["城市"] == "上海" for x in rows)
          and all(x["大区"] == "华东" for x in rows)
          and len({x["月份"] for x in rows}) == 12)
    record("P-6a region_month --filter 城市=上海", "只剩华东（上海店）行，月数不变",
           f"{len(rows)} 行，全部 城市=上海 且 大区=华东，月数={len({x['月份'] for x in rows})}",
           "PASS" if r["ok"] and ok else "FAIL")

    # ---- P-6b 城市=火星市（值非法→静默回退） ----
    r = run("retail", "region_month", {"城市": "火星市"})
    record("P-6b region_month --filter 城市=火星市", "静默回退=全量 36 行（D14；实际全量见下）",
           f"无报错，返回 {len(rows)} 行（=该报表无筛选全量行数）",
           "PASS" if r["ok"] and len(r["rows"]) == 96 else "DEVIATE",
           "注：TESTPLAN 写'全量 36 行'，引擎无筛选全量本身为 96 行（filters 并入 GROUP BY）；"
           "回退行为本身符合 D14")

    # ---- P-6c 维度名非法 ----
    r = run("retail", "region_month", {"不存在的维度": "任意值"})
    record("P-6c region_month --filter 不存在的维度=任意值", "维度名非法必须报错并列出可用维度",
           r["err"] if not r["ok"] else f"未报错，返回 {len(r['rows'])} 行",
           "PASS" if not r["ok"] and "可用" in r["err"] else "FAIL")

    # ---- P-6d 组合 filter 空结果 ----
    r = run("retail", "store_rank", {"大区": "华北", "城市": "厦门"})
    record("P-6d store_rank 大区=华北+城市=厦门", "组合 filter 空结果合法（返回空集）",
           f"{'返回 ' + str(len(r['rows'])) + ' 行' if r['ok'] else r['err']}",
           "PASS" if r["ok"] and r["rows"] == [] else "FAIL")

    # ---- R11 筹备门店观察 ----
    opts = filter_options("retail", "store_rank")
    r = run("retail", "store_rank", {"城市": "北京"})
    names = sorted({x["门店"] for x in r["rows"]}) if r["ok"] else []
    record("R11 store_rank --filter 城市=北京", "返回北京在营门店行；筹备店无行；白名单观察",
           f"返回门店={names}；城市白名单={opts.get('城市')}",
           "PASS" if r["ok"] and names == ["北京国贸店"] else "DEVIATE",
           "观察点：白名单来自 mart distinct（有流水门店），筹备店不在白名单/结果中")

    # ---- R8 注入三连（retail） ----
    r = run("retail", "region_month", {"不存在的维度": "X"})
    record("R8a retail 维度名非法", "报错", r["err"] if not r["ok"] else "未报错",
           "PASS" if not r["ok"] else "FAIL")
    r = run("retail", "region_month", {"城市": "火星市"})
    record("R8b retail 维度值非法", "静默回退全量", f"返回 {len(r['rows'])} 行，无报错",
           "PASS" if r["ok"] and len(r["rows"]) == 96 else "FAIL")
    sql, params = build_query("retail", "region_month", {"城市": INJ})
    r = run("retail", "region_month", {"城市": INJ})
    lit_in_sql = INJ in sql
    lit_in_rows = any(INJ in str(v) for x in r.get("rows", []) for v in x.values())
    record("R8c retail 注入串 城市=华东' OR 1=1--", "静默回退；SQL 与结果不含注入字面量",
           f"返回 {len(r.get('rows', []) if r['ok'] else [])} 行；字面量进SQL={lit_in_sql}，"
           f"进结果={lit_in_rows}；params={params}",
           "PASS" if r["ok"] and not lit_in_sql and not lit_in_rows and len(r["rows"]) == 96 else "FAIL",
           f"SQL={sql}")

    # ---- P-7a hro bu_month 行业=文体 ----
    r = run("hro", "bu_month", {"行业": "文体"})
    rows = r.get("rows", [])
    ok = all(x["行业"] == "文体" for x in rows) and len({x["月份"] for x in rows}) == 12
    record("P-7a bu_month --filter 行业=文体", "只剩文体客户挂的行",
           f"{len(rows)} 行，全部 行业=文体={all(x['行业'] == '文体' for x in rows)}，"
           f"月数={len({x['月份'] for x in rows})}，事业部={sorted({str(x['事业部']) for x in rows})}",
           "PASS" if r["ok"] and ok else "FAIL")

    # ---- P-7b customer_ar 客户级别=S级（黄灯值作筛选值） ----
    opts = filter_options("hro", "customer_ar")
    r = run("hro", "customer_ar", {"客户级别": "S级"})
    rows = r.get("rows", [])
    record("P-7b customer_ar --filter 客户级别=S级", "只剩越枚举客户所在行（黄灯值可作筛选值）",
           f"客户级别白名单={opts.get('客户级别')}；返回 {len(rows)} 行："
           f"{[(x['客户'], x['客户级别']) for x in rows]}",
           "PASS" if r["ok"] and rows and all(x["客户级别"] == "S级" for x in rows) else "FAIL")

    # ---- P-7c industry_month 客户级别=Z级（值非法→静默回退） ----
    r = run("hro", "industry_month", {"客户级别": "Z级"})
    record("P-7c industry_month --filter 客户级别=Z级", "静默回退全量（D14）",
           f"无报错，返回 {len(r.get('rows', []) if r['ok'] else [])} 行（该报表无筛选全量=162）",
           "PASS" if r["ok"] and len(r["rows"]) == 162 else "FAIL")

    # ---- P-7d group_rank 事业部=不存在的维度（TESTPLAN 原文） ----
    r = run("hro", "group_rank", {"事业部": "不存在的维度"})
    record("P-7d group_rank --filter 事业部=不存在的维度（TESTPLAN 原文）",
           "TESTPLAN 预期类别：维度名非法报错",
           ("无报错，静默回退返回 " + str(len(r["rows"])) + " 行") if r["ok"] else r["err"],
           "DEVIATE" if r["ok"] else "PASS",
           "注：'事业部' 是 group_rank 的合法筛选维度名，'不存在的维度' 是非法【值】——"
           "按 P-08/D14 语义应静默回退；TESTPLAN 文字把本案标注为'维度名非法报错'，"
           "与自身 P-08 语义冲突。补充真名非法对照案见下条。")
    r = run("hro", "group_rank", {"不存在的维度": "X"})
    record("P-7d' group_rank --filter 不存在的维度=X（对照：真名非法）", "报错并列可用维度",
           r["err"] if not r["ok"] else "未报错", "PASS" if not r["ok"] else "FAIL")

    # ---- H7 hro 注入三连 ----
    r = run("hro", "group_rank", {"不存在的维度": "X"})
    record("H7a hro 维度名非法", "报错", r["err"] if not r["ok"] else "未报错",
           "PASS" if not r["ok"] else "FAIL")
    r = run("hro", "customer_ar", {"客户": "不存在公司"})
    record("H7b hro 维度值非法", "静默回退全量", f"返回 {len(r.get('rows', []) if r['ok'] else [])} 行（全量 25）",
           "PASS" if r["ok"] and len(r["rows"]) == 25 else "FAIL")
    sql, params = build_query("hro", "customer_ar", {"客户": INJ})
    r = run("hro", "customer_ar", {"客户": INJ})
    lit = INJ in sql or any(INJ in str(v) for x in r.get("rows", []) for v in x.values())
    record("H7c hro 注入串", "静默回退；SQL 与结果不含注入字面量",
           f"返回 {len(r.get('rows', []) if r['ok'] else [])} 行；字面量出现={lit}；params={params}",
           "PASS" if r["ok"] and not lit and len(r["rows"]) == 25 else "FAIL")

    (HERE / "filter_checks.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n== filter/injection 合计 {len(results)} 条：PASS "
          f"{sum(1 for x in results if x['verdict'] == 'PASS')} / DEVIATE "
          f"{sum(1 for x in results if x['verdict'] == 'DEVIATE')} / FAIL "
          f"{sum(1 for x in results if x['verdict'] == 'FAIL')} ==")


if __name__ == "__main__":
    main()
