# -*- coding: utf-8 -*-
"""v0.5 开放接口验收 · 命题 Agent 密封答案生成器（确定性，重复运行哈希一致）。

数据来源（全部独立于被测实现 mcp_server.py / semantic/inspect.py）：
  1. instances/<inst>/metrics.yml            → metrics_list_{inst}.json / caliber_sample.json
  2. instances/<inst>/instance.yml           → list_instances.json
  3. instances/<inst>/dashboard.yml          → list_reports_{inst}.json
  4. tests/v0.4/{S1_retail,S2_hro}/expected/answer.json
                                             → report_rows_{inst}_{report}.json（pandas 投影，
                                               时间键保持 YYYY-MM 密封格式）+ 3 个筛选投影期望
  5. data/runs/history_restaurant.json       → status_restaurant.json（最近跑批事实）
     其余账套无 history_*.json + instances/<i>/pipeline/target/run_results.json 节点统计
                                             → status_{inst}.json（灯色禁止集，理由内嵌）
  6. 行为 Case 规格静态内嵌（must_contain 清单从 yml 派生）

约定：不写任何时间戳进 expected/（保证 sha256 幂等）；json 用 indent=1 + sort_keys。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd  # noqa: E402  （任务要求：投影用 pandas 独立完成）
import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
EXPECTED = HERE / "expected"

INSTANCES = ["restaurant", "retail", "hro", "sales"]  # 固定顺序（列表展示序自定，判分按集合）
TITLES = {}
for _i in INSTANCES:
    TITLES[_i] = yaml.safe_load(
        (ROOT / f"instances/{_i}/instance.yml").read_text(encoding="utf-8"))["title"]

ANSWER = {
    "retail": ROOT / "tests/v0.4/S1_retail/expected/answer.json",
    "hro": ROOT / "tests/v0.4/S2_hro/expected/answer.json",
}

# 六指标口径抽样（跨四账套覆盖 percent/非 percent、比率/金额/计数）
CALIBER_PICKS = [
    ("retail", "毛利率"), ("retail", "库存周转率"), ("hro", "回款率"),
    ("hro", "人均产值"), ("sales", "收入"), ("restaurant", "客单数"),
]

# 行为 Case 里"可用清单"关键词（从 yml 派生，禁止手写漂移）
RETAIL_REPORT_KEYS = None  # 下面从 dashboard.yml 读取


def dump(name: str, obj) -> None:
    (EXPECTED / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")


def py(v):
    """pandas/numpy 标量 → 纯 Python 标量（np.int64 不可 json 序列化）。"""
    if v is None:
        return None
    if hasattr(v, "item"):
        return v.item()
    return v


def metrics_of(inst: str) -> list[dict]:
    y = yaml.safe_load((ROOT / f"instances/{inst}/metrics.yml").read_text(encoding="utf-8"))
    out = []
    for m in y["metrics"]:
        out.append({
            "name": m["name"],
            "expr": m["expr"],
            "format": m.get("format"),
            "desc": m.get("desc"),
        })
    return out


def rows_frame(report: dict) -> pd.DataFrame:
    return pd.DataFrame(report["rows"], dtype=object)


def main() -> int:
    EXPECTED.mkdir(parents=True, exist_ok=True)
    for old in EXPECTED.glob("*.json"):
        old.unlink()

    # ---------- 1. list_instances ----------
    dump("list_instances.json", {
        "promise": "R-10 账套列表；R-11 约定：下划线开头目录是测试副本，永不视为正式账套",
        "instances": [{"name": i, "title": TITLES[i]} for i in INSTANCES],
    })

    # ---------- 2. metrics_list / list_reports / caliber ----------
    caliber = []
    for inst in INSTANCES:
        dump(f"metrics_list_{inst}.json", {
            "instance": inst,
            "source": f"instances/{inst}/metrics.yml",
            "metrics": metrics_of(inst),
        })
        dash = yaml.safe_load(
            (ROOT / f"instances/{inst}/dashboard.yml").read_text(encoding="utf-8"))
        reps = [{
            "key": r["key"], "title": r["title"], "dimension": r["dimension"],
            "metrics": list(r.get("metrics", [])),
        } for r in dash["reports"]]
        dump(f"list_reports_{inst}.json", {"instance": inst, "reports": reps})
        if inst == "retail":
            RETAIL_REPORT_KEYS = [r["key"] for r in reps]

    catalogs = {i: {m["name"]: m for m in metrics_of(i)} for i in INSTANCES}
    for inst, name in CALIBER_PICKS:
        m = catalogs[inst][name]
        caliber.append({
            "instance": inst, "metric": name, "expr": m["expr"],
            "format": m["format"], "desc_nonempty": bool(m["desc"]),
            "desc": m["desc"],
        })
    dump("caliber_sample.json", {"promise": "get_caliber 单指标口径：expr 一致、desc 非空、format 一致",
                                 "samples": caliber})

    # ---------- 3. report_rows（pandas 投影，保持密封行序与数值类型） ----------
    for inst, path in ANSWER.items():
        ans = json.loads(path.read_text(encoding="utf-8"))
        for key, rep in ans.items():
            df = rows_frame(rep)
            rows = [{c: py(v) for c, v in rec.items()} for rec in df.to_dict("records")]
            assert len(rows) == len(rep["rows"])
            dump(f"report_rows_{inst}_{key}.json",
                 {"instance": inst, "report": key, "columns": list(rep["columns"]),
                  "rows": rows, "sealed_from": str(path.relative_to(ROOT)).replace("\\", "/")})

    # ---------- 4. 筛选投影期望（行子集，pandas 布尔掩码） ----------
    ans_r = json.loads(ANSWER["retail"].read_text(encoding="utf-8"))
    ans_h = json.loads(ANSWER["hro"].read_text(encoding="utf-8"))
    filters = []

    def seal_filter(case: str, ans: dict, key: str, mask_col: str, mask_val: str,
                    f_dim: str, f_val: str, basis: str):
        rep = ans[key]
        df = rows_frame(rep)
        sub = df[df[mask_col] == mask_val]
        rows = [{c: py(v) for c, v in rec.items()} for rec in sub.to_dict("records")]
        assert rows, f"{case}: 筛选投影为空，密封中止"
        dump(f"report_filtered_{case}.json",
             {"case": case, "instance": ans is ans_r and "retail" or "hro", "report": key,
              "filter_dim": f_dim, "filter_value": f_val,
              "columns": list(rep["columns"]), "rows": rows, "basis": basis})
        filters.append(case)

    # 城市=上海 → 只剩华东（上海店）行（v0.4 TESTPLAN P-6a 定谳）
    seal_filter("retail_region_month_cityshanghai", ans_r, "region_month",
                "大区", "华东", "城市", "上海",
                "v0.4 P-6a：上海店属华东且华东仅上海 → 期望=answer.json 大区=华东 12 行")
    seal_filter("retail_channel_month_ecommerce", ans_r, "channel_month",
                "渠道", "电商", "渠道", "电商", "筛选值即行维度值 → 行子集")
    seal_filter("hro_industry_month_internet", ans_h, "industry_month",
                "行业", "互联网", "行业", "互联网", "筛选值即行维度值 → 行子集")

    # ---------- 5. status_{inst}.json ----------
    hist = json.loads((ROOT / "data/runs/history_restaurant.json").read_text(encoding="utf-8"))
    latest = hist[-1]
    assert latest["status"] == "green", "restaurant 最新跑批应 green，密封中止"

    def rr_facts(inst: str) -> dict:
        p = ROOT / f"instances/{inst}/pipeline/target/run_results.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        import collections
        cnt = collections.Counter(r["status"] for r in d["results"])
        return {k: int(cnt.get(k, 0)) for k in ("success", "pass", "warn", "error", "fail")}

    dump("status_restaurant.json", {
        "instance": "restaurant",
        "has_history": True,
        "latest": {
            "run_id": latest["run_id"],
            "status": latest["status"],
            "trigger": latest["trigger"],
            "started_at": latest["started_at"],
            "finished_at": latest["finished_at"],
            "ingest_ok": latest["ingest_ok"],
            "compile_returncode": latest["compile_returncode"],
            "dbt_returncode": latest["dbt_returncode"],
            "counts": latest["counts"],
        },
        "light": {"expect": "green", "forbid": ["red"]},
        "missing_sources_must_be_empty": True,
        "basis": "data/runs/history_restaurant.json 最新条目 + R-10 数据健康诊断承诺",
    })

    LIGHT_RULE = {
        # 灯色禁止集依据：红=退出码非零（无失败证据）；黄=warn>0（run_results 有 warn）；
        # 绿=全过。无 history 的账套允许"无跑批"类取值（none/unknown/never/gray/null…），
        # 但若报灯色则不得与 run_results 事实矛盾（承诺：黄=warn，绿=全过，红=退出码非零）。
        "sales": {"forbid": ["yellow", "red"], "warn_baseline": 0},
        "retail": {"forbid": ["green", "red"], "warn_baseline": 10},
        "hro": {"forbid": ["green", "red"], "warn_baseline": 4},
    }
    for inst in ("sales", "retail", "hro"):
        assert not (ROOT / f"data/runs/history_{inst}.json").exists(), \
            f"{inst} 出现 history 文件，status 期望需重新密封"
        facts = rr_facts(inst)
        assert facts.get("warn", 0) == LIGHT_RULE[inst]["warn_baseline"], \
            f"{inst} warn 基线漂移：{facts}"
        dump(f"status_{inst}.json", {
            "instance": inst,
            "has_history": False,
            "latest": None,
            "light": {"expect": None, "forbid": LIGHT_RULE[inst]["forbid"]},
            "missing_sources_must_be_empty": True,
            "basis": (f"无 data/runs/history_{inst}.json（允许报'无跑批'）；"
                      f"pipeline/target/run_results.json 节点统计={facts}；"
                      "承诺：黄=warn、绿=全过、红=退出码非零——灯色不得与之矛盾"),
            "run_results_facts": facts,
        })

    # ---------- 6. behavior.json（行为 Case 规格，must_contain 从 yml 派生） ----------
    retail_dims_filters = ["城市"]  # retail region_month filters
    identify = {
        "names": INSTANCES,
        "titles": [TITLES[i] for i in INSTANCES],
    }
    dump("behavior.json", {
        "note": "每个 Case 的证据由测试 Agent 按 TESTPLAN §5 存入 judge/actual/b_*.json，"
                "judge 只对证据做机械断言；错误标记词表见 judge/score.py ERROR_HINT",
        "cases": {
            "B01_unknown_instance_list_metrics": {
                "tool": "list_metrics", "kind": "mcp_error", "must_error": True,
                "identify_all": identify,
                "call": "list_metrics(instance='_no_such_instance__')"},
            "B02_unknown_report_query": {
                "tool": "query_report", "kind": "mcp_error", "must_error": True,
                "must_contain_any": RETAIL_REPORT_KEYS,
                "call": "query_report(instance='retail', report='_no_such_report__')"},
            "B03_unknown_metric_caliber": {
                "tool": "get_caliber", "kind": "mcp_error", "must_error": True,
                "must_contain_any": ["销售额", "毛利", "库存周转率"],
                "call": "get_caliber(instance='retail', metric='_no_such_metric__')"},
            "B04_unknown_filter_dimension": {
                "tool": "query_report", "kind": "mcp_error", "must_error": True,
                "must_contain_any": retail_dims_filters,
                "call": "query_report(instance='retail', report='region_month', "
                        "filters={'不存在的维度__': '任意值'})",
                "basis": "P-08：维度名非法必须报错并列出可用维度（region_month 声明 filters=[城市]）"},
            "B05_inject_filter_mcp": {
                "tool": "query_report", "kind": "rows_equal_full",
                "instance": "retail", "report": "region_month", "expect_rows": 36,
                "filter_value": "华东' OR 1=1--",
                "must_not_contain": ["OR 1=1"],
                "sealed_ref": "report_rows_retail_region_month.json",
                "basis": "D14：维度值非法 → 静默回退不过滤；P-08/N-10；"
                         "行集逐值吻合 = WHERE 语义未被注入改变（等价于'无注入字面量进 SQL'的可观察断言）"},
            "B06_http_no_key": {
                "kind": "http_status", "path": "/api/open/status?instance=retail",
                "api_key": None, "expect_status": [401, 403],
                "basis": "R-10：X-API-Key 鉴权"},
            "B07_http_bad_key": {
                "kind": "http_status", "path": "/api/open/status?instance=retail",
                "api_key": "cl-invalid-key-for-test-000", "expect_status": [401, 403]},
            "B08_inject_filter_http": {
                "kind": "http_rows_equal_full",
                "path": "/api/open/reports/region_month/data?instance=retail",
                "inject_params": {"filter": "大区:华东' OR 1=1--", "大区": "华东' OR 1=1--"},
                "expect_rows": 36, "must_not_contain": ["OR 1=1"],
                "basis": "若端点声明了 filter 参数则用该参数注入重试并记录（观察项）；"
                         "未声明时多余参数必须被静默忽略（200 + 全量 36 行），不得 5xx"},
            "B09_limit_clamp": {
                "kind": "limit",
                "mcp": {"instance": "retail", "report": "monthly_kpi",
                        "limit": 100000, "rows_le": 12, "must_error": False},
                "http_limit_5": {"path": "/api/open/reports/monthly_kpi/data?instance=retail&limit=5",
                                 "rows_eq": 5, "basis": "R-10 原文示例 limit=5"},
                "http_bad_limit": {"path": "/api/open/reports/monthly_kpi/data?instance=retail&limit=abc",
                                   "forbid_status": [500, 502, 503]},
                "basis": "§5.4 报表参数白名单/钳制惯例；越界不得崩溃、不得返回超过全量"},
            "B10_underscore_excluded": {
                "kind": "list_instances_clean", "probe_dir": "_probe_openapi_tmp",
                "basis": "R-11：下划线开头实例目录是测试副本，永不视为正式账套"},
            "B11_audit_jsonl": {
                "kind": "audit", "file": "logs/mcp_audit.jsonl", "must_grow": True,
                "basis": "R-10：全调用审计在 logs/mcp_audit.jsonl"},
            "B12_unknown_instance_status": {
                "tool": "get_data_status", "kind": "mcp_error", "must_error": True,
                "identify_all": identify,
                "call": "get_data_status(instance='_no_such_instance__')"},
            "B13_inspect_restaurant_joins": {
                "tool": "semantic.inspect (CLI)", "kind": "inspect_joins",
                "instance": "restaurant",
                "must_contain_pairs": [
                    ["orders", "dishes", "菜品编码"],
                    ["orders", "stores", "门店编码"],
                ],
                "arrow_forms": ["orders←菜品编码—dishes", "orders←门店编码—stores"],
                "must_mention": ["config_draft"],
                "basis": "R-11：inspect 产出 join 建议；restaurant 既有两个可关联键对"
                         "（orders.菜品编码↔dishes.dish_code、orders.门店编码↔stores.store_code，"
                         "出处 instances/restaurant/sources.yml），建议清单必须包含这 2 条既有关联"},
        },
    })

    # ---------- 7. manifest.sha256 ----------
    lines = []
    for p in sorted(EXPECTED.glob("*.json")):
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{h}  {p.name}")
    # 二进制写，避免 Windows 文本模式把 \n 翻译成 \r\l（sha256sum -c 会把 \r 并进文件名）
    (EXPECTED / "manifest.sha256").write_bytes(
        ("\n".join(lines) + "\n").encode("utf-8"))

    print(f"sealed {len(lines) + 1} files into {EXPECTED}")
    for ln in lines:
        print(" ", ln[:19], ln[22:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
