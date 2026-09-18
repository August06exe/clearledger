# -*- coding: utf-8 -*-
"""评审 Agent 机械判分器：密封答案（expected/answer.json）vs 实际结果（actual_*.json）。

判分口径（评审职责书 A）：
- 对齐：按答案的「维度列组合键」对齐（时间列归一到 YYYY-MM，如 2025-09-01 → 2025-09）。
- 数值：金额/计数容差 0.01；比率容差 1e-6（两侧均应为原始小数；
  若 actual ≈ expected×100 判 percent_literal 嫌疑＝测试侧格式 bug，仍记失败）。
- null 必须精确是 null（null vs 0 记失败）。
- 列集合校验：actual 列名 vs answer 列名（缺失/多余分列）。
- 行集膨胀（实现把 filters 并入 GROUP BY 导致一键多行）：记 failure kind=inflation；
  另做「投影回答案粒度后可加指标能否对上」的**诊断**（只诊断、不判分——
  投影对齐会掩盖粒度与口径差异，不作为通过依据）。
- 判分依据只有 answer.json / actual_*.json / dashboard.yml（维度×指标定义），
  不读引擎代码结论、不读测试报告的任何判定。

输出：tests/v0.4/judge/score_round1.json + stdout 人类可读摘要。
只读运行，不改任何引擎/实例/答案文件。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

ANSWER = {
    "retail": ROOT / "tests/v0.4/S1_retail/expected/answer.json",
    "hro": ROOT / "tests/v0.4/S2_hro/expected/answer.json",
}
ACTUAL = {
    "retail": HERE / "actual_retail.json",
    "hro": HERE / "actual_hro.json",
}
DASHBOARD = {
    "retail": ROOT / "instances/retail/dashboard.yml",
    "hro": ROOT / "instances/hro/dashboard.yml",
}

MONEY_TOL = 0.01
RATIO_TOL = 1e-6
# 比率列（与 SPEC §8「比率 round 4」口径一致；周转率/占比/率均按比率容差判）
RATIO_COLS = {"毛利率", "回款率", "电商销售占比", "库存周转率"}
# 人均类=两指标相除，跨组求和无意义（诊断投影时同比率列一样跳过）
NON_ADDITIVE = RATIO_COLS | {"人均人力成本", "人均产值"}

_DATE_RE = re.compile(r"^(\d{4}-\d{2})-\d{2}")


def norm_key_val(v):
    """维度键归一：月份 2025-09-01 → 2025-09；其余原样（None 保持 None）。"""
    if v is None:
        return None
    s = str(v)
    m = _DATE_RE.match(s)
    return m.group(1) if m else s


def tol_of(col: str) -> float:
    return RATIO_TOL if col in RATIO_COLS else MONEY_TOL


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def judge_report(ans: dict, act: dict, metrics: list[str]) -> dict:
    ans_cols: list[str] = ans["columns"]
    act_cols: list[str] = act["columns"]
    dim_cols = [c for c in ans_cols if c not in metrics]  # 答案侧维度键列

    rep: dict = {
        "answer_rows": len(ans["rows"]),
        "actual_rows": len(act["rows"]),
        "columns_answer": ans_cols,
        "columns_actual": act_cols,
        "columns_missing": [c for c in ans_cols if c not in act_cols],
        "columns_extra": [c for c in act_cols if c not in ans_cols],
    }
    rep["columns_ok"] = not rep["columns_missing"] and not rep["columns_extra"]

    failures: list[dict] = []
    if not set(dim_cols) <= set(act_cols):
        rep["cases_total"] = rep["cases_passed"] = 0
        rep["cases_failed"] = 0
        rep["failures"] = [{"kind": "columns", "detail": "维度列缺失，无法对齐"}]
        rep["structural_fail"] = True
        return rep

    # 索引 actual 行（键 → 行列表）
    act_by_key: dict[tuple, list[dict]] = {}
    for r in act["rows"]:
        act_by_key.setdefault(tuple(norm_key_val(r.get(c)) for c in dim_cols), []).append(r)

    ans_keys = set()
    multi_keys, matched_keys, passed = set(), 0, 0
    for row in ans["rows"]:
        key = tuple(norm_key_val(row.get(c)) for c in dim_cols)
        ans_keys.add(key)
        hits = act_by_key.get(key, [])
        key_disp = {c: row.get(c) for c in dim_cols}
        if not hits:
            failures.append({"kind": "missing_key", "key": key_disp,
                             "expected_row": row})
            continue
        if len(hits) > 1:
            multi_keys.add(key)
            failures.append({"kind": "inflation", "key": key_disp,
                             "actual_row_count": len(hits),
                             "note": "实现把 filters 并入 GROUP BY → 一键多行（行集粒度与答案不一致）"})
            continue
        matched_keys += 1
        act_row = hits[0]
        case_fail = 0
        for col in ans_cols:
            if col in dim_cols or col not in act_cols:
                continue
            ev, av = row.get(col), act_row.get(col)
            if ev is None and av is None:
                continue
            if ev is None or av is None:
                case_fail += 1
                failures.append({"kind": "null_mismatch", "key": key_disp, "column": col,
                                 "expected": ev, "actual": av})
                continue
            if not (is_num(ev) and is_num(av)):
                if str(ev) != str(av):
                    case_fail += 1
                    failures.append({"kind": "value", "key": key_disp, "column": col,
                                     "expected": ev, "actual": av, "diff": None})
                continue
            diff = round(av - ev, 6)
            if abs(diff) <= tol_of(col) + 1e-9:
                # 百分数嫌疑：值在容差内但形如 expected×100（比率列才会出现）
                if col in RATIO_COLS and ev != 0 and abs(av - ev * 100) <= MONEY_TOL:
                    case_fail += 1
                    failures.append({"kind": "percent_literal", "key": key_disp,
                                     "column": col, "expected": ev, "actual": av,
                                     "note": "actual 疑似百分数字面量（测试侧格式 bug）"})
            else:
                case_fail += 1
                f = {"kind": "value", "key": key_disp, "column": col,
                     "expected": ev, "actual": av, "diff": diff}
                if col in RATIO_COLS and ev != 0 and abs(av - ev * 100) <= MONEY_TOL:
                    f["kind"] = "percent_literal"
                    f["note"] = "actual 疑似百分数字面量（测试侧格式 bug）"
                failures.append(f)
        if case_fail == 0:
            passed += 1

    # actual 多出的键
    extra_keys = sorted(k for k in act_by_key if k not in ans_keys)
    for k in extra_keys:
        failures.append({"kind": "extra_key",
                         "key": {c: v for c, v in zip(dim_cols, k)},
                         "actual_row_count": len(act_by_key[k])})

    # 行序（信息项）：列集一致时比较键序列
    order_match = None
    if rep["columns_ok"]:
        seq_a = [tuple(norm_key_val(r.get(c)) for c in dim_cols) for r in ans["rows"]]
        seq_b = [tuple(norm_key_val(r.get(c)) for c in dim_cols) for r in act["rows"]]
        order_match = seq_a == seq_b

    # 膨胀诊断（只诊断、不判分）：把 actual 投影回答案粒度，可加指标求和后比对
    diag = None
    if multi_keys:
        additive = [m for m in metrics if m not in NON_ADDITIVE and m in act_cols]
        diag = {"note": "投影回答案粒度仅为诊断，不参与判分（比率列不可加，跳过）",
                "additive_cols_checked": additive, "keys_diagnosed": len(multi_keys),
                "cells_matched": 0, "cells_mismatched": 0, "mismatch_samples": []}
        for row in ans["rows"]:
            key = tuple(norm_key_val(row.get(c)) for c in dim_cols)
            if key not in multi_keys:
                continue
            hits = act_by_key[key]
            for col in additive:
                s = sum(r.get(col) or 0 for r in hits if is_num(r.get(col)) or r.get(col) is None)
                s = round(float(s), 2)
                ev = row.get(col)
                if is_num(ev) and abs(s - ev) <= MONEY_TOL + 1e-9:
                    diag["cells_matched"] += 1
                else:
                    diag["cells_mismatched"] += 1
                    if len(diag["mismatch_samples"]) < 5:
                        diag["mismatch_samples"].append(
                            {"key": {c: row.get(c) for c in dim_cols}, "column": col,
                             "expected": ev, "actual_projected_sum": s})

    rep.update({
        "cases_total": len(ans["rows"]),
        "cases_passed": passed,
        "cases_failed": len(ans["rows"]) - passed,
        "keys_matched_1to1": matched_keys,
        "keys_inflated": len(multi_keys),
        "keys_extra_in_actual": len(extra_keys),
        "order_match": order_match,
        "inflation_diagnostic": diag,
        "failures": failures,
        "structural_fail": False,
    })
    return rep


def main() -> int:
    dashboards = {n: yaml.safe_load(DASHBOARD[n].read_text(encoding="utf-8"))
                  for n in ANSWER}
    out: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tolerance": {"money_count": MONEY_TOL, "ratio": RATIO_TOL},
        "rule": "对齐=答案维度列组合键（月份归一 YYYY-MM）；null 必须两侧皆 null；"
                "膨胀（一键多行）记 failure，投影重聚合仅诊断不判分",
        "instances": {},
    }
    total = passed = failed = 0
    for inst in ("retail", "hro"):
        ans = json.loads(ANSWER[inst].read_text(encoding="utf-8"))
        act = json.loads(ACTUAL[inst].read_text(encoding="utf-8"))
        rep_metrics = {r["key"]: list(r.get("metrics", []))
                       for r in dashboards[inst]["reports"]}
        reports = {}
        i_total = i_pass = i_fail = 0
        for key in ans:
            rep = judge_report(ans[key], act[key], rep_metrics.get(key, []))
            reports[key] = rep
            i_total += rep["cases_total"]
            i_pass += rep["cases_passed"]
            i_fail += rep["cases_failed"]
        out["instances"][inst] = {"reports": reports,
                                  "cases_total": i_total, "cases_passed": i_pass,
                                  "cases_failed": i_fail,
                                  "reports_all_green": all(
                                      reports[k]["columns_ok"] and reports[k]["cases_failed"] == 0
                                      for k in reports)}
        total += i_total
        passed += i_pass
        failed += i_fail

    out["grand_total"] = {"cases_total": total, "cases_passed": passed,
                          "cases_failed": failed,
                          "all_green": failed == 0 and all(
                              out["instances"][n]["reports_all_green"] for n in out["instances"])}
    (HERE / "score_round1.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 人类可读摘要 ----
    print("=" * 88)
    print("v0.4 机械判分摘要（answer.json vs actual_*.json；金额容差 0.01 / 比率容差 1e-6）")
    print("=" * 88)
    for inst in ("retail", "hro"):
        print(f"\n【{inst}】")
        print(f"  {'报表':<16}{'Case':>5}{'通过':>5}{'失败':>5}  列集  行序  备注")
        for key, rep in out["instances"][inst]["reports"].items():
            notes = []
            if not rep["columns_ok"]:
                notes.append(f"列差 missing={rep['columns_missing']} extra={rep['columns_extra']}")
            if rep.get("keys_inflated"):
                notes.append(f"膨胀键 {rep['keys_inflated']} 个（一键多行）")
            if rep.get("keys_extra_in_actual"):
                notes.append(f"多出键 {rep['keys_extra_in_actual']} 个")
            if rep.get("keys_missing"):
                pass
            miss = sum(1 for f in rep["failures"] if f["kind"] == "missing_key")
            if miss:
                notes.append(f"缺键 {miss} 个")
            order = rep["order_match"]
            print(f"  {key:<16}{rep['cases_total']:>5}{rep['cases_passed']:>5}"
                  f"{rep['cases_failed']:>5}  {'OK' if rep['columns_ok'] else 'X':^4}"
                  f"  {'-' if order is None else ('=' if order else 'X')}"
                  f"  {'；'.join(notes)}")
            for f in rep["failures"][:12]:
                if f["kind"] in ("value", "null_mismatch", "percent_literal"):
                    print(f"      ✗ {f['key']} | {f['column']}: 期望 {f['expected']!r} "
                          f"实际 {f['actual']!r} 差 {f.get('diff')}"
                          + (f" [{f['kind']}]" if f["kind"] != "value" else ""))
                elif f["kind"] == "inflation":
                    print(f"      ✗ {f['key']} | 该键在实际结果中被拆成 {f['actual_row_count']} 行")
                elif f["kind"] == "missing_key":
                    print(f"      ✗ {f['key']} | 实际结果中无此键")
                elif f["kind"] == "extra_key":
                    print(f"      ✗ {f['key']} | 实际结果多出此键（{f['actual_row_count']} 行）")
            if len(rep["failures"]) > 12:
                print(f"      …（其余 {len(rep['failures']) - 12} 条失败明细见 score_round1.json）")
            diag = rep.get("inflation_diagnostic")
            if diag:
                print(f"      [诊断·不判分] 投影回答案粒度后可加指标：对上 {diag['cells_matched']} 格 / "
                      f"对不上 {diag['cells_mismatched']} 格")
        st = out["instances"][inst]
        print(f"  小计：Case {st['cases_total']}，通过 {st['cases_passed']}，失败 {st['cases_failed']}"
              f"{'（全部报表列集一致）' if st['reports_all_green'] else '（存在列集差异）'}")
    g = out["grand_total"]
    print("\n" + "=" * 88)
    print(f"总计：Case {g['cases_total']} / 通过 {g['cases_passed']} / 失败 {g['cases_failed']}"
          f"  →  {'100% 通过' if g['all_green'] else '未 100% 通过（失败明细见上与 score_round1.json）'}")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(main())
