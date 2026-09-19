# -*- coding: utf-8 -*-
"""v0.5 开放接口验收 · 机械判分器（评审/判分职责，三权分立：只读证据，不读引擎与测试报告）。

判分口径（继承 v0.4 定谳）：
- 对齐：按密封答案的维度列组合键；时间键归一（2025-09-01 / 2025-09-01T00:00:00 → 2025-09）。
- 数值：金额/计数容差 0.01；比率容差 1e-6；null 必须精确是 null（null vs 0 记失败）；
  actual ≈ expected×100 的比率列判 percent_literal 嫌疑＝失败（测试侧格式 bug 也算失败）。
- 一键多行记 inflation 失败；actual 多出键记 extra_key 失败；行序只记录不判。
- 列集合：密封列必须全部存在；额外列默认失败（筛选 Case 允许额外出现筛选维度列）。
- 行为 Case：证据信封见 TESTPLAN §5，断言规格密封于 expected/behavior.json。

用法：
  python tests/v0.5/judge/score.py [--tag round1] [--actual-dir DIR] [--strict-manifest]
输出：tests/v0.5/judge/score_<tag>.json + stdout 人类可读摘要。幂等：同 tag 覆盖。
只读运行，不改任何引擎/实例/答案文件。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent           # tests/v0.5/judge
V05 = HERE.parent                                # tests/v0.5
ROOT = V05.parents[1]                            # 仓库根
EXPECTED = V05 / "expected"
DEFAULT_ACTUAL = HERE / "actual"
AUDIT_FILE = ROOT / "logs" / "mcp_audit.jsonl"

MONEY_TOL = 0.01
RATIO_TOL = 1e-6
RATIO_COLS = {"毛利率", "回款率", "电商销售占比", "库存周转率"}
SIX_TOOLS = ["list_instances", "list_metrics", "list_reports",
             "query_report", "get_data_status", "get_caliber"]
ERROR_HINT = re.compile(r"错误|报错|异常|未知|不存在|未找到|不支持|非法|invalid|unknown|"
                        r"not\s*found|no\s+such|error|exception", re.IGNORECASE)
INJECT_MARK = "OR 1=1"
LIGHT_NORM = {"绿": "green", "黄": "yellow", "红": "red"}
_LIGHT_RE = re.compile(r"^(green|yellow|red|绿|黄|红)$", re.IGNORECASE)
_RUNID_RE = re.compile(r"\d{8}_\d{6}(?:_[0-9a-zA-Z]{2,12})?")
_TIME_FULL = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$")
_TIME_PREF = re.compile(r"^(\d{4}-\d{2})-\d{2}")
_MISS_KEY = re.compile(r"miss|缺|absent|not_import|未导入|未命中", re.IGNORECASE)


# ---------------------------------------------------------------- 基础工具
def norm_key_val(v):
    """维度键归一：时间列 2025-09-01 / 2025-09-01T00:00:00 → 2025-09；其余原样。"""
    if v is None:
        return None
    s = str(v).strip()
    m = _TIME_FULL.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = _TIME_PREF.match(s)
    return m.group(1) if m else s


def tol_of(col: str) -> float:
    return RATIO_TOL if col in RATIO_COLS else MONEY_TOL


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def ws(s) -> str | None:
    return None if s is None else " ".join(str(s).split())


def deep_texts(obj):
    """递归收集所有字符串值（含 dict 键名）。"""
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(deep_texts(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(deep_texts(v))
    return out


def find_lights(obj):
    """收集疑似灯色取值（green/yellow/red 或中文，无论键名）。"""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and _LIGHT_RE.match(v.strip()):
                out.append(LIGHT_NORM.get(v.strip().lower(), v.strip().lower()))
            else:
                out.extend(find_lights(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(find_lights(v))
    return out


def find_run_ids(obj):
    out: list[str] = []
    for t in deep_texts(obj):
        out.extend(_RUNID_RE.findall(t))
    return out


def find_missing_lists(obj, path=""):
    """键名疑似'缺失/未导入'的列表 → [(path, len)]。"""
    out: list[tuple[str, int]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            if isinstance(v, list) and _MISS_KEY.search(str(k)):
                out.append((p, len(v)))
            out.extend(find_missing_lists(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(find_missing_lists(v, f"{path}[{i}]"))
    return out


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


class CaseStore:
    """收集判分结果。"""

    def __init__(self):
        self.rows: list[dict] = []

    def add(self, case: str, verdict: str, detail: str = "", failures=None):
        assert verdict in ("PASS", "FAIL", "NOT_RUN")
        self.rows.append({"case": case, "verdict": verdict,
                          "detail": detail, "failures": failures or []})
        return self.rows[-1]

    def counts(self):
        p = sum(1 for r in self.rows if r["verdict"] == "PASS")
        f = sum(1 for r in self.rows if r["verdict"] == "FAIL")
        n = sum(1 for r in self.rows if r["verdict"] == "NOT_RUN")
        return {"total": len(self.rows), "passed": p, "failed": f, "not_run": n}


# ---------------------------------------------------------------- 行集判分（继承 v0.4 机制）
def judge_rows(case: str, exp: dict, act_doc: dict | None,
               metrics: list[str], allow_extra_cols: list[str] | None = None) -> dict:
    if act_doc is None or not isinstance(act_doc, dict) or \
            "columns" not in act_doc or "rows" not in act_doc:
        return CaseStore().add(case, "NOT_RUN" if act_doc is None else "FAIL",
                               "actual 缺失或非 {columns, rows} 标准形")
    exp_cols: list[str] = exp["columns"]
    act_cols: list[str] = list(act_doc["columns"])
    act_rows: list[dict] = act_doc["rows"]
    dim_cols = [c for c in exp_cols if c not in metrics]
    failures: list[dict] = []
    extra_allowed = set(allow_extra_cols or [])

    missing_cols = [c for c in exp_cols if c not in act_cols]
    extra_cols = [c for c in act_cols if c not in exp_cols and c not in extra_allowed]
    if missing_cols:
        failures.append({"kind": "columns_missing", "columns": missing_cols})
    if extra_cols:
        failures.append({"kind": "columns_extra", "columns": extra_cols,
                         "note": "允许额外列仅为筛选维度列" if extra_allowed else None})
    if missing_cols:  # 维度列缺失则无法对齐
        return {"case": case, "verdict": "FAIL", "detail": "密封列缺失，无法对齐",
                "failures": failures, "cases_total": len(exp["rows"]),
                "cases_passed": 0, "order_match": None}

    act_by_key: dict[tuple, list[dict]] = {}
    for r in act_rows:
        act_by_key.setdefault(tuple(norm_key_val(r.get(c)) for c in dim_cols), []).append(r)

    ans_keys: set[tuple] = set()
    passed = 0
    for row in exp["rows"]:
        key = tuple(norm_key_val(row.get(c)) for c in dim_cols)
        ans_keys.add(key)
        hits = act_by_key.get(key, [])
        key_disp = {c: row.get(c) for c in dim_cols}
        if not hits:
            failures.append({"kind": "missing_key", "key": key_disp})
            continue
        if len(hits) > 1:
            failures.append({"kind": "inflation", "key": key_disp,
                             "actual_row_count": len(hits)})
            continue
        act_row = hits[0]
        bad = 0
        for col in exp_cols:
            if col in dim_cols or col not in act_cols:
                continue
            ev, av = row.get(col), act_row.get(col)
            if ev is None and av is None:
                continue
            if ev is None or av is None:
                bad += 1
                failures.append({"kind": "null_mismatch", "key": key_disp,
                                 "column": col, "expected": ev, "actual": av})
                continue
            if not (is_num(ev) and is_num(av)):
                if str(ev) != str(av):
                    bad += 1
                    failures.append({"kind": "value", "key": key_disp, "column": col,
                                     "expected": ev, "actual": av})
                continue
            diff = round(av - ev, 6)
            if abs(diff) <= tol_of(col) + 1e-9:
                if col in RATIO_COLS and ev != 0 and abs(av - ev * 100) <= MONEY_TOL:
                    bad += 1
                    failures.append({"kind": "percent_literal", "key": key_disp,
                                     "column": col, "expected": ev, "actual": av})
            else:
                bad += 1
                failures.append({"kind": "value", "key": key_disp, "column": col,
                                 "expected": ev, "actual": av, "diff": diff})
        if bad == 0:
            passed += 1

    for k in sorted(k for k in act_by_key if k not in ans_keys):
        failures.append({"kind": "extra_key",
                         "key": {c: v for c, v in zip(dim_cols, k)},
                         "actual_row_count": len(act_by_key[k])})

    order = None
    if not missing_cols and not extra_cols:
        seq_a = [tuple(norm_key_val(r.get(c)) for c in dim_cols) for r in exp["rows"]]
        seq_b = [tuple(norm_key_val(r.get(c)) for c in dim_cols) for r in act_rows]
        order = seq_a == seq_b

    verdict = "PASS" if not failures else "FAIL"
    detail = (f"行数 期望{len(exp['rows'])}/实际{len(act_rows)}；"
              f"格通过 {passed}/{len(exp['rows'])}"
              + (f"；行序一致={order}" if order is not None else ""))
    return {"case": case, "verdict": verdict, "detail": detail,
            "failures": failures[:50], "failure_count": len(failures),
            "cases_total": len(exp["rows"]), "cases_passed": passed, "order_match": order}


# ---------------------------------------------------------------- 主流程
def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="round1")
    ap.add_argument("--actual-dir", default=str(DEFAULT_ACTUAL))
    ap.add_argument("--strict-manifest", action="store_true")
    args = ap.parse_args()
    actual_dir = Path(args.actual_dir)

    # ---- 密封完整性 ----
    manifest_ok, drift = True, []
    manifest = EXPECTED / "manifest.sha256"
    if not manifest.exists():
        manifest_ok = False
        drift.append("manifest.sha256 缺失")
    else:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            h, name = line.split(None, 1)
            p = EXPECTED / name.strip()
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
                manifest_ok = False
                drift.append(f"{name.strip()} 哈希不符或缺失")
    if drift:
        print("!! 警告：expected/ 与 manifest 不一致（先重跑 tests/v0.5/generate.py 重新密封）：")
        for d in drift:
            print("   -", d)
        if args.strict_manifest:
            print("!! --strict-manifest：硬失败退出")
            return 2

    exp = lambda name: load_json(EXPECTED / name)  # noqa: E731

    # 报表 → 指标清单（来自密封 list_reports，用于区分维度列/指标列）
    rep_metrics: dict[tuple[str, str], list[str]] = {}
    for inst in ("sales", "restaurant", "retail", "hro"):
        lr = exp(f"list_reports_{inst}.json")
        for r in lr["reports"]:
            rep_metrics[(inst, r["key"])] = list(r["metrics"])

    def rows_actual(fname: str):
        doc = load_json(actual_dir / fname)
        if doc is None:
            return None
        if isinstance(doc, dict) and "parsed" in doc and isinstance(doc["parsed"], dict):
            doc = doc["parsed"]
        return doc if isinstance(doc, dict) and "columns" in doc and "rows" in doc else None

    def envelope(fname: str) -> dict | None:
        d = load_json(actual_dir / fname)
        return d if isinstance(d, dict) else None

    def raw_of(env: dict) -> str:
        parts = [env.get("raw") or ""]
        if isinstance(env.get("parsed"), (dict, list)):
            parts.append(json.dumps(env["parsed"], ensure_ascii=False))
        return "\n".join(str(x) for x in parts)

    num = CaseStore()
    beh = CaseStore()

    # ================= 数值 Case =================
    # N-00 六工具存在
    tools = load_json(actual_dir / "mcp_tools.json")
    if tools is None:
        num.add("N-00", "NOT_RUN", "缺少 actual/mcp_tools.json")
    else:
        names = [t.get("name") for t in tools if isinstance(t, dict)]
        miss = [t for t in SIX_TOOLS if t not in names]
        no_schema = [t.get("name") for t in tools
                     if isinstance(t, dict) and not t.get("inputSchema")]
        ok = not miss and not no_schema
        num.add("N-00", "PASS" if ok else "FAIL",
                f"工具数={len(names)}；缺={miss or '无'}；无schema={no_schema or '无'}")

    # N-01 list_instances
    li_exp = exp("list_instances.json")
    env = envelope("list_instances.json")
    if env is None:
        num.add("N-01", "NOT_RUN", "缺少 actual/list_instances.json")
    else:
        parsed = env.get("parsed", env)
        items = parsed if isinstance(parsed, list) else (
            parsed.get("instances") or parsed.get("data") or [])
        names = [it.get("name") if isinstance(it, dict) else str(it) for it in items]
        titles = {it.get("name"): it.get("title") for it in items if isinstance(it, dict)}
        exp_names = {i["name"] for i in li_exp["instances"]}
        exp_titles = {i["name"]: i["title"] for i in li_exp["instances"]}
        f = []
        if set(names) != exp_names:
            f.append({"kind": "names", "missing": sorted(exp_names - set(names)),
                      "extra": sorted(set(names) - exp_names)})
        bad_t = {n: t for n, t in titles.items() if exp_titles.get(n) not in (None, t)}
        if bad_t:
            f.append({"kind": "titles", "detail": bad_t})
        if any(str(n).startswith("_") for n in names):
            f.append({"kind": "underscore_leak", "detail": "返回含下划线开头条目"})
        num.add("N-01", "FAIL" if f else "PASS",
                f"账套 {sorted(names)}", f)

    # N-02~05 metrics 目录
    for i, inst in enumerate(("sales", "restaurant", "retail", "hro"), start=2):
        me = exp(f"metrics_list_{inst}.json")
        env = envelope(f"metrics_list_{inst}.json")
        case = f"N-{i:02d}"
        if env is None:
            num.add(case, "NOT_RUN", f"缺少 actual/metrics_list_{inst}.json")
            continue
        parsed = env.get("parsed", env)
        items = parsed.get("metrics") if isinstance(parsed, dict) else parsed
        items = items if isinstance(items, list) else []
        by_name = {m.get("name"): m for m in items if isinstance(m, dict)}
        f = []
        exp_names = {m["name"] for m in me["metrics"]}
        if {n for n in by_name if n is not None} != exp_names:
            f.append({"kind": "names", "missing": sorted(exp_names - set(by_name)),
                      "extra": sorted(set(by_name) - exp_names)})
        for m in me["metrics"]:
            a = by_name.get(m["name"])
            if a is None:
                continue
            if ws(a.get("expr")) != ws(m["expr"]):
                f.append({"kind": "expr", "metric": m["name"],
                          "expected": m["expr"], "actual": a.get("expr")})
            af = a.get("format")
            if af is not None and af != m["format"]:
                f.append({"kind": "format", "metric": m["name"],
                          "expected": m["format"], "actual": af})
            ad = a.get("desc")
            if ad is not None and m["desc"] is not None and ws(ad) != ws(m["desc"]):
                f.append({"kind": "desc_mismatch", "metric": m["name"],
                          "expected": m["desc"], "actual": ad})
        num.add(case, "FAIL" if f else "PASS",
                f"{inst} 指标数 期望{len(me['metrics'])}/实际{len(by_name)}", f)

    # N-06~17 全量行集
    report_plan = ([("retail", k) for k in
                    ["monthly_kpi", "region_month", "category_month",
                     "channel_month", "store_rank", "supplier_rank"]] +
                   [("hro", k) for k in
                    ["monthly_kpi", "bu_month", "group_rank",
                     "customer_ar", "industry_month", "contract_ledger"]])
    for i, (inst, key) in enumerate(report_plan, start=6):
        case = f"N-{i:02d}"
        erows = exp(f"report_rows_{inst}_{key}.json")
        adoc = rows_actual(f"report_rows_{inst}_{key}.json")
        rep = judge_rows(case, erows, adoc, rep_metrics[(inst, key)])
        num.rows.append(rep)

    # N-18~20 筛选投影
    filtered_plan = [
        ("N-18", "report_filtered_retail_region_month_cityshanghai.json",
         ("retail", "region_month"), "城市"),
        ("N-19", "report_filtered_retail_channel_month_ecommerce.json",
         ("retail", "channel_month"), "渠道"),
        ("N-20", "report_filtered_hro_industry_month_internet.json",
         ("hro", "industry_month"), "行业"),
    ]
    for case, fname, (inst, key), fdim in filtered_plan:
        erows = exp(fname)
        adoc = rows_actual(fname)
        rep = judge_rows(case, erows, adoc, rep_metrics[(inst, key)],
                         allow_extra_cols=[fdim])
        num.rows.append(rep)

    # N-21~24 get_data_status
    status_plan = [
        ("N-21", "restaurant", True),
        ("N-22", "sales", False),
        ("N-23", "retail", False),
        ("N-24", "hro", False),
    ]
    for case, inst, has_hist in status_plan:
        st = exp(f"status_{inst}.json")
        env = envelope(f"status_{inst}.json")
        if env is None:
            num.add(case, "NOT_RUN", f"缺少 actual/status_{inst}.json")
            continue
        parsed = env.get("parsed", env)
        lights = set(find_lights(parsed)) | {
            LIGHT_NORM.get(t.strip().lower(), t.strip().lower())
            for t in deep_texts(parsed) if _LIGHT_RE.match(t.strip())}
        runids = set(find_run_ids(parsed)) | set(
            m.group(0) for t in deep_texts(parsed) for m in [_RUNID_RE.search(t)] if m)
        f = []
        if has_hist:
            rid = st["latest"]["run_id"]
            if rid not in runids and rid not in raw_of(env):
                f.append({"kind": "run_id", "expected": rid,
                          "found": sorted(runids)[:5]})
            if "green" not in lights:
                f.append({"kind": "light", "expected": "green", "found": sorted(lights)})
            if "red" in lights:
                f.append({"kind": "light_forbid", "forbid": ["red"]})
        else:
            bad = sorted(set(st["light"]["forbid"]) & lights)
            if bad:
                f.append({"kind": "light_forbid", "forbid": st["light"]["forbid"],
                          "found": bad,
                          "note": st["basis"]})
        miss_lists = [(p, n) for p, n in find_missing_lists(parsed) if n > 0]
        if miss_lists:
            f.append({"kind": "missing_sources_nonempty", "lists": miss_lists})
        num.add(case, "FAIL" if f else "PASS",
                f"{inst} 灯色候选={sorted(lights) or '无'}；run_id 候选={sorted(runids)[:2] or '无'}", f)

    # N-25 get_caliber 六连
    cal = exp("caliber_sample.json")
    f = []
    sub_details = []
    for s in cal["samples"]:
        fname = f"caliber_{s['instance']}_{s['metric']}.json"
        env = envelope(fname)
        if env is None:
            f.append({"kind": "missing", "file": fname})
            continue
        parsed = env.get("parsed", env)
        obj = None
        if isinstance(parsed, dict):
            if parsed.get("name") == s["metric"] or parsed.get("metric") == s["metric"] \
                    or "expr" in parsed:
                obj = parsed
            else:
                stack = [parsed]
                while stack and obj is None:
                    cur = stack.pop()
                    if isinstance(cur, dict):
                        if cur.get("name") == s["metric"] or cur.get("metric") == s["metric"]:
                            obj = cur
                        else:
                            stack.extend(cur.values())
                    elif isinstance(cur, list):
                        stack.extend(cur)
        if obj is None:
            f.append({"kind": "metric_not_found", "metric": s["metric"],
                      "file": fname})
            continue
        aexpr = obj.get("expr") or obj.get("formula") or obj.get("公式")
        if ws(aexpr) != ws(s["expr"]):
            f.append({"kind": "expr", "metric": s["metric"],
                      "expected": s["expr"], "actual": aexpr})
        afmt = obj.get("format")
        if afmt is not None and afmt != s["format"]:
            f.append({"kind": "format", "metric": s["metric"],
                      "expected": s["format"], "actual": afmt})
        adesc = obj.get("desc") or obj.get("description") or obj.get("口径") or obj.get("说明")
        if adesc is None or not str(adesc).strip():
            f.append({"kind": "desc_empty", "metric": s["metric"],
                      "note": "get_caliber 承诺单指标口径：desc 必须非空"})
        elif s["desc"] is not None and ws(adesc) != ws(s["desc"]):
            f.append({"kind": "desc_mismatch", "metric": s["metric"],
                      "expected": s["desc"], "actual": adesc})
        sub_details.append(f"{s['instance']}/{s['metric']}")
    if not sub_details and all(
            not (actual_dir / f"caliber_{s['instance']}_{s['metric']}.json").exists()
            for s in cal["samples"]):
        num.add("N-25", "NOT_RUN", "缺少 actual/caliber_*.json 全部 6 份")
    else:
        num.add("N-25", "FAIL" if f else "PASS",
                f"抽样 {len(sub_details)}/6：{'、'.join(sub_details)}", f)

    # N-26~29 list_reports
    for i, inst in enumerate(("retail", "hro", "sales", "restaurant"), start=26):
        case = f"N-{i:02d}"
        lr = exp(f"list_reports_{inst}.json")
        env = envelope(f"list_reports_{inst}.json")
        if env is None:
            num.add(case, "NOT_RUN", f"缺少 actual/list_reports_{inst}.json")
            continue
        parsed = env.get("parsed", env)
        items = parsed.get("reports") if isinstance(parsed, dict) else parsed
        items = items if isinstance(items, list) else []
        by_key = {r.get("key"): r for r in items if isinstance(r, dict)}
        f = []
        exp_keys = {r["key"] for r in lr["reports"]}
        if set(by_key) != exp_keys:
            f.append({"kind": "keys", "missing": sorted(exp_keys - set(by_key)),
                      "extra": sorted(set(by_key) - exp_keys)})
        for r in lr["reports"]:
            a = by_key.get(r["key"])
            if a is None:
                continue
            if a.get("title") is not None and a["title"] != r["title"]:
                f.append({"kind": "title", "key": r["key"],
                          "expected": r["title"], "actual": a["title"]})
            if a.get("dimension") is not None and a["dimension"] != r["dimension"]:
                f.append({"kind": "dimension", "key": r["key"],
                          "expected": r["dimension"], "actual": a["dimension"]})
            am = a.get("metrics")
            if am is not None and sorted(map(str, am)) != sorted(r["metrics"]):
                f.append({"kind": "metrics", "key": r["key"],
                          "expected": r["metrics"], "actual": am})
        num.add(case, "FAIL" if f else "PASS",
                f"{inst} 报表数 期望{len(lr['reports'])}/实际{len(by_key)}", f)

    # N-30 HTTP 报表目录 == 密封 list_reports_retail
    lr = exp("list_reports_retail.json")
    env = envelope("http_reports_retail.json")
    if env is None:
        num.add("N-30", "NOT_RUN", "缺少 actual/http_reports_retail.json")
    else:
        f = []
        if env.get("http_status") != 200:
            f.append({"kind": "http_status", "expected": 200,
                      "actual": env.get("http_status")})
        parsed = env.get("parsed", env)
        items = parsed.get("reports") if isinstance(parsed, dict) else parsed
        items = items if isinstance(items, list) else []
        keys = {r.get("key") for r in items if isinstance(r, dict)}
        exp_keys = {r["key"] for r in lr["reports"]}
        if keys != exp_keys:
            f.append({"kind": "keys", "missing": sorted(exp_keys - keys),
                      "extra": sorted(keys - exp_keys)})
        num.add("N-30", "FAIL" if f else "PASS",
                f"HTTP 报表目录 key 数={len(keys)} 期望={len(exp_keys)}", f)

    # N-31/32 HTTP 报表数据行集
    for case, inst, key in (("N-31", "retail", "monthly_kpi"),
                            ("N-32", "hro", "contract_ledger")):
        erows = exp(f"report_rows_{inst}_{key}.json")
        adoc = rows_actual(f"http_report_data_{inst}_{key}.json")
        env_status = None
        raw = load_json(actual_dir / f"http_report_data_{inst}_{key}.json")
        if isinstance(raw, dict):
            env_status = raw.get("http_status")
        rep = judge_rows(case, erows, adoc, rep_metrics[(inst, key)])
        if env_status is not None and env_status != 200 and rep["verdict"] != "NOT_RUN":
            rep = dict(rep, verdict="FAIL",
                       failures=[{"kind": "http_status", "expected": 200,
                                  "actual": env_status}] + rep["failures"])
        num.rows.append(rep)

    # N-33 HTTP 指标目录 hro
    me = exp("metrics_list_hro.json")
    env = envelope("http_metrics_hro.json")
    if env is None:
        num.add("N-33", "NOT_RUN", "缺少 actual/http_metrics_hro.json")
    else:
        parsed = env.get("parsed", env)
        items = parsed.get("metrics") if isinstance(parsed, dict) else parsed
        items = items if isinstance(items, list) else []
        names = {m.get("name") for m in items if isinstance(m, dict)}
        exp_names = {m["name"] for m in me["metrics"]}
        f = []
        if env.get("http_status") != 200:
            f.append({"kind": "http_status", "expected": 200, "actual": env.get("http_status")})
        if names != exp_names:
            f.append({"kind": "names", "missing": sorted(exp_names - names),
                      "extra": sorted(names - exp_names)})
        num.add("N-33", "FAIL" if f else "PASS",
                f"HTTP 指标数={len(names)} 期望={len(exp_names)}", f)

    # N-34 HTTP status restaurant
    st = exp("status_restaurant.json")
    env = envelope("http_status_restaurant.json")
    if env is None:
        num.add("N-34", "NOT_RUN", "缺少 actual/http_status_restaurant.json")
    else:
        parsed = env.get("parsed", env)
        texts = deep_texts(parsed)
        lights = {LIGHT_NORM.get(t.strip().lower(), t.strip().lower())
                  for t in texts if _LIGHT_RE.match(t.strip())}
        rid = st["latest"]["run_id"]
        f = []
        if env.get("http_status") != 200:
            f.append({"kind": "http_status", "expected": 200, "actual": env.get("http_status")})
        if "green" not in lights:
            f.append({"kind": "light", "expected": "green", "found": sorted(lights)})
        if rid not in raw_of(env):
            f.append({"kind": "run_id", "expected": rid})
        num.add("N-34", "FAIL" if f else "PASS",
                f"HTTP 灯色候选={sorted(lights) or '无'}", f)

    # ================= 行为 Case（规格密封于 behavior.json） =================
    spec = exp("behavior.json")["cases"]
    INST_NAMES = ["sales", "restaurant", "retail", "hro"]
    INST_TITLES = ["演示销售公司", "演示连锁餐饮", "荟品汇零售连锁", "睿才人力"]

    def err_case(case_id: str, must_contain_any=None, identify_all=False):
        nn = case_id.split("_")[0][1:]                       # "B01" → "01"
        cands = sorted(actual_dir.glob(f"b{nn}_*.json"))     # 前缀匹配（短名/全名均可）
        if not cands:
            beh.add(case_id, "NOT_RUN", f"缺少 actual/b{nn}_*.json 证据文件")
            return
        env = envelope(cands[0].name)
        if env is None:
            beh.add(case_id, "NOT_RUN", f"{cands[0].name} 不是合法 JSON 信封")
            return
        raw = raw_of(env)
        is_err = (env.get("ok") is False) or bool(ERROR_HINT.search(raw))
        f = []
        if not is_err:
            f.append({"kind": "must_error", "note": "证据未呈现错误形态"})
        if must_contain_any and not any(x in raw for x in must_contain_any):
            f.append({"kind": "must_contain_any", "candidates": must_contain_any})
        if identify_all:
            missing = [n for n, t in zip(INST_NAMES, INST_TITLES)
                       if n not in raw and t not in raw]
            if missing:
                f.append({"kind": "identify_all", "unidentified": missing,
                          "names": INST_NAMES})
        beh.add(case_id, "FAIL" if f else "PASS",
                f"ok={env.get('ok')}；raw 前 120 字={raw[:120]!r}", f)

    err_case("B01_unknown_instance_list_metrics", identify_all=True)
    err_case("B02_unknown_report_query",
             must_contain_any=spec["B02_unknown_report_query"]["must_contain_any"])
    err_case("B03_unknown_metric_caliber",
             must_contain_any=spec["B03_unknown_metric_caliber"]["must_contain_any"])
    err_case("B04_unknown_filter_dimension",
             must_contain_any=spec["B04_unknown_filter_dimension"]["must_contain_any"])

    # B-05 MCP 注入筛选 → 静默回退全量
    bspec = spec["B05_inject_filter_mcp"]
    env = envelope("b05_inject_mcp.json")
    if env is None:
        beh.add("B05_inject_filter_mcp", "NOT_RUN", "缺少 actual/b05_inject_mcp.json")
    else:
        adoc = rows_actual("b05_inject_mcp.json")
        raw = raw_of(env)
        f = []
        if env.get("ok") is False or ERROR_HINT.search(raw):
            f.append({"kind": "must_not_error", "note": "值非法应静默回退（D14）"})
        rep = judge_rows("B05", exp(bspec["sealed_ref"]), adoc,
                         rep_metrics[("retail", "region_month")])
        if rep["verdict"] != "PASS":
            f.append({"kind": "rows_not_full", "detail": rep["detail"],
                      "failures": rep["failures"][:10]})
        if any(INJECT_MARK in t for t in deep_texts(raw)):
            f.append({"kind": "literal_in_response", "mark": INJECT_MARK})
        beh.add("B05_inject_filter_mcp", "FAIL" if f else "PASS", rep["detail"], f)

    # B-06/07 HTTP 鉴权
    for case_id, fname in (("B06_http_no_key", "b06_http_nokey.json"),
                           ("B07_http_bad_key", "b07_http_badkey.json")):
        env = envelope(fname)
        if env is None:
            beh.add(case_id, "NOT_RUN", f"缺少 actual/{fname}")
            continue
        code = env.get("http_status")
        ok = code in spec[case_id]["expect_status"]
        beh.add(case_id, "PASS" if ok else "FAIL",
                f"http_status={code}（期望 ∈ {spec[case_id]['expect_status']}）",
                [] if ok else [{"kind": "http_status", "expected": spec[case_id]["expect_status"],
                                "actual": code}])

    # B-08 HTTP 注入参数
    bspec = spec["B08_inject_filter_http"]
    env = envelope("b08_inject_http.json")
    if env is None:
        beh.add("B08_inject_filter_http", "NOT_RUN", "缺少 actual/b08_inject_http.json")
    else:
        adoc = rows_actual("b08_inject_http.json")
        raw = raw_of(env)
        f = []
        code = env.get("http_status")
        if code is not None and code != 200:
            f.append({"kind": "http_status", "expected": 200, "actual": code})
        rep = judge_rows("B08", exp("report_rows_retail_region_month.json"), adoc,
                         rep_metrics[("retail", "region_month")])
        if rep["verdict"] != "PASS":
            f.append({"kind": "rows_not_full", "detail": rep["detail"],
                      "failures": rep["failures"][:10]})
        if any(INJECT_MARK in t for t in deep_texts(raw)):
            f.append({"kind": "literal_in_response", "mark": INJECT_MARK})
        beh.add("B08_inject_filter_http", "FAIL" if f else "PASS", rep["detail"], f)

    # B-09 limit 钳制
    env = envelope("b09_limit.json")
    if env is None:
        beh.add("B09_limit_clamp", "NOT_RUN", "缺少 actual/b09_limit.json")
    else:
        b = spec["B09_limit_clamp"]
        f = []
        m = env.get("mcp") or {}
        if m.get("ok") is False or m.get("error"):
            f.append({"kind": "mcp_error", "detail": m.get("raw", "")[:160]})
        elif not is_num(m.get("rows")) or m["rows"] > b["mcp"]["rows_le"]:
            f.append({"kind": "mcp_rows_le", "limit": b["mcp"]["limit"], "rows": m.get("rows"),
                      "rows_le": b["mcp"]["rows_le"]})
        h5 = env.get("http_limit_5") or {}
        if h5.get("http_status") != 200 or h5.get("rows") != b["http_limit_5"]["rows_eq"]:
            f.append({"kind": "http_limit_5", "expected": {"status": 200, "rows": 5},
                      "actual": {k: h5.get(k) for k in ("http_status", "rows")}})
        hb = env.get("http_bad_limit") or {}
        if hb.get("http_status") in b["http_bad_limit"]["forbid_status"]:
            f.append({"kind": "http_bad_limit_5xx", "status": hb.get("http_status")})
        beh.add("B09_limit_clamp", "FAIL" if f else "PASS",
                f"mcp.rows={m.get('rows')}；http limit=5 → rows={h5.get('rows')}；"
                f"http limit=abc → status={hb.get('http_status')}", f)

    # B-10 下划线实例排除（探测法）
    env = envelope("b10_underscore.json")
    if env is None:
        beh.add("B10_underscore_excluded", "NOT_RUN", "缺少 actual/b10_underscore.json")
    else:
        if not env.get("probe_created"):
            beh.add("B10_underscore_excluded", "NOT_RUN",
                    "证据未含 probe_created=true（未按探测法执行）")
        else:
            parsed = env.get("parsed", env)
            items = parsed if isinstance(parsed, list) else (
                parsed.get("instances") or parsed.get("data") or [])
            names = [it.get("name") if isinstance(it, dict) else str(it) for it in items]
            leaked = sorted({n for n in names if str(n).startswith("_")})
            ok = not leaked
            beh.add("B10_underscore_excluded", "PASS" if ok else "FAIL",
                    f"账套={sorted(names)}；下划线泄漏={leaked or '无'}",
                    [] if ok else [{"kind": "underscore_leak", "names": leaked}])

    # B-11 审计 JSONL
    env = envelope("b11_audit.json")
    audit_fail = []
    audit_note = ""
    if not AUDIT_FILE.exists():
        audit_fail.append({"kind": "file_missing", "file": str(AUDIT_FILE)})
    else:
        lines = [ln for ln in AUDIT_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
        bad = 0
        for ln in lines:
            try:
                json.loads(ln)
            except Exception:
                bad += 1
        if bad:
            audit_fail.append({"kind": "invalid_jsonl_lines", "count": bad})
        audit_note = f"JSONL 行数={len(lines)}"
        if env is None:
            beh.add("B11_audit_jsonl", "NOT_RUN",
                    f"缺少 actual/b11_audit.jsonl（{audit_note}）")
        else:
            before, after = env.get("lines_before"), env.get("lines_after")
            if not (is_num(before) and is_num(after) and after > before):
                audit_fail.append({"kind": "must_grow",
                                   "lines_before": before, "lines_after": after})
            beh.add("B11_audit_jsonl", "FAIL" if audit_fail else "PASS",
                    f"{audit_note}；before={before} after={after}", audit_fail)

    # B-12 get_data_status 未知账套
    err_case("B12_unknown_instance_status", identify_all=True)

    # B-13 体检器 join 建议
    bspec = spec["B13_inspect_restaurant_joins"]
    env = envelope("b13_inspect_restaurant.json")
    if env is None:
        beh.add("B13_inspect_restaurant_joins", "NOT_RUN",
                "缺少 actual/b13_inspect_restaurant.json")
    else:
        raw = str(env.get("raw") or "")
        f = []
        if env.get("exit_code") not in (None, 0):
            f.append({"kind": "exit_code", "actual": env.get("exit_code")})
        joined = ["".join(str(x).split()) for x in raw.splitlines()]
        nospace = "".join(raw.split())
        for pair, arrow in zip(bspec["must_contain_pairs"], bspec["arrow_forms"]):
            hit = any(all(tok in line for tok in pair) for line in joined) \
                or arrow in nospace
            if not hit:
                f.append({"kind": "join_pair_missing", "tokens": pair, "arrow": arrow})
        if not any(bspec["must_mention"][0] in t for t in deep_texts(raw)):
            f.append({"kind": "must_mention", "tokens": bspec["must_mention"]})
        beh.add("B13_inspect_restaurant_joins", "FAIL" if f else "PASS",
                f"exit={env.get('exit_code')}；报告 {len(raw.splitlines())} 行", f)

    # ================= 汇总 =================
    nc, bc = num.counts(), beh.counts()
    all_pass = nc["failed"] == 0 and nc["not_run"] == 0 and \
        bc["failed"] == 0 and bc["not_run"] == 0
    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "manifest_verified": manifest_ok,
        "tolerance": {"money_count": MONEY_TOL, "ratio": RATIO_TOL},
        "numeric": {"cases": num.rows, **nc},
        "behavior": {"cases": beh.rows, **bc},
        "grand": {"total": nc["total"] + bc["total"],
                  "passed": nc["passed"] + bc["passed"],
                  "failed": nc["failed"] + bc["failed"],
                  "not_run": nc["not_run"] + bc["not_run"],
                  "all_green": all_pass},
    }
    out_path = HERE / f"score_{args.tag}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 人类可读摘要 ----
    print("=" * 92)
    print(f"v0.5 开放接口判分（tag={args.tag}；金额容差 0.01 / 比率容差 1e-6；"
          f"manifest {'OK' if manifest_ok else '漂移!!'}）")
    print("=" * 92)
    for title, store in (("数值 Case", num), ("行为 Case", beh)):
        print(f"\n【{title}】")
        for r in store.rows:
            mark = {"PASS": "PASS", "FAIL": "✗ FAIL", "NOT_RUN": "- NOT_RUN"}[r["verdict"]]
            print(f"  [{mark:9s}] {r['case']:<38} {r['detail']}")
            for x in r["failures"][:6]:
                print(f"        · {json.dumps(x, ensure_ascii=False)[:180]}")
            if len(r["failures"]) > 6:
                print(f"        …（其余 {len(r['failures']) - 6} 条见 {out_path.name}）")
    g = out["grand"]
    print("\n" + "=" * 92)
    print(f"总计：Case {g['total']} / PASS {g['passed']} / FAIL {g['failed']} / "
          f"NOT_RUN {g['not_run']}  →  {'100% 通过' if g['all_green'] else '未 100% 通过'}")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    sys.exit(main())
