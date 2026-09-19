# -*- coding: utf-8 -*-
"""v0.5 开放接口验收测试 · 测试 Agent 采集脚本（round1）。
职责：只执行、只写 judge/actual/；不改引擎、不改配置、不触发跑批、不读 expected/。
按 TESTPLAN §5 收集顺序：P-0 工具发现 → 目录类 → 报表类 → status/caliber → HTTP 面 → 行为 Case（B-13 单独最后跑）。
"""
import sys, os, json, asyncio, shutil, subprocess
import urllib.request, urllib.error
from urllib.parse import quote

ROOT = r"D:\Workshop\3000-Projects\3005-DA-AI Native数据底座系统"
sys.path.insert(0, ROOT)
ACTUAL = os.path.join(ROOT, "tests", "v0.5", "judge", "actual")
os.makedirs(ACTUAL, exist_ok=True)
LOG = []

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def save(name, obj):
    p = os.path.join(ACTUAL, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print("  [saved]", name)


def note(case, msg):
    line = f"[{case}] {msg}"
    LOG.append(line)
    print(line)


# ---------------- MCP 进程内直调（TESTPLAN §2.1 原样） ----------------
import mcp_server  # noqa: E402


def find_server():
    """先按惯用名找，找不到就扫描模块属性（运行时内省，不读源码）。"""
    for n in ("mcp", "server", "app", "clearledger"):
        obj = getattr(mcp_server, n, None)
        if obj is not None and hasattr(obj, "call_tool"):
            return obj, n
    for n in dir(mcp_server):
        obj = getattr(mcp_server, n, None)
        if obj is not None and hasattr(obj, "call_tool"):
            return obj, n
    raise RuntimeError("未找到具备 call_tool 的 server 对象")


SRV, SRV_NAME = find_server()
print(f"server object resolved via module attr: {SRV_NAME}")


async def mcp_call(name, args=None):
    try:
        result = await SRV.call_tool(name, args or {})
        content = result[0] if isinstance(result, tuple) else result
        text = content[0].text if hasattr(content[0], "text") else str(content[0])
    except Exception as e:  # noqa: BLE001 —— 错误本身也是测试证据
        return False, None, f"{type(e).__name__}: {e}"
    try:
        return True, json.loads(text), text
    except Exception:
        return True, None, text


LOOP = asyncio.new_event_loop()


def mcp(name, args=None):
    return LOOP.run_until_complete(mcp_call(name, args))


async def discover_tools():
    tools = await SRV.list_tools()
    return [{"name": t.name, "description": getattr(t, "description", ""),
             "inputSchema": getattr(t, "inputSchema", None)} for t in tools]


def prop_for(tool, *candidates, default=None):
    """按 inputSchema 找参数名（candidates 为子串匹配，小写）。找不到回退 default。"""
    for t in TOOLS:
        if t["name"] == tool:
            props = (t.get("inputSchema") or {}).get("properties") or {}
            for c in candidates:
                for p in props:
                    if c in p.lower():
                        return p
            return default
    return default


# ---------------- HTTP（TESTPLAN §2.2 原样） ----------------
BASE = "http://127.0.0.1:8620"
with open(os.path.join(ROOT, "data", "openapi_keys.json"), encoding="utf-8") as f:
    API_KEY = next(iter(json.load(f)))


def http_get(path, api_key=API_KEY, timeout=30):
    req = urllib.request.Request(BASE + path)
    if api_key is not None:
        req.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body), body
            except Exception:
                return r.status, None, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body), body
        except Exception:
            return e.code, None, body


# ---------------- 通用归一 ----------------
def envelope(ok, raw, parsed, http_status=None, **extra):
    d = {"ok": ok, "http_status": http_status, "raw": raw, "parsed": parsed}
    d.update(extra)
    return d


def to_rows_form(parsed):
    """报表类返回归一为 {columns, rows} 标准形；无法归一时原样保存并备注。"""
    if isinstance(parsed, dict):
        cols = parsed.get("columns")
        rows = parsed.get("rows")
        if rows is None and isinstance(parsed.get("data"), list):
            rows = parsed["data"]
        if cols is None and isinstance(parsed.get("fields"), list):
            cols = parsed["fields"]
        if isinstance(cols, list) and isinstance(rows, list):
            extra_keys = [k for k in parsed.keys() if k not in ("columns", "rows", "data", "fields")]
            form = {"columns": cols, "rows": rows}
            if extra_keys:
                form["extra_top_level_keys_ignored"] = extra_keys
            return form
    return {"columns": [], "rows": [], "unparsed_nonstandard": parsed}


# ================= P-0 工具发现 =================
print("== P-0 discover_tools ==")
TOOLS = LOOP.run_until_complete(discover_tools())
save("mcp_tools.json", TOOLS)
note("N-00", f"tools={[t['name'] for t in TOOLS]}")
_qr_props = None
for t in TOOLS:
    if t["name"] == "query_report":
        _qr_props = list(((t.get("inputSchema") or {}).get("properties") or {}).keys())
note("N-00", f"query_report inputSchema properties={_qr_props}")

# ================= N-01 list_instances =================
ok, parsed, raw = mcp("list_instances", {})
save("list_instances.json", envelope(ok, raw, parsed))
note("N-01", f"ok={ok} parsed_type={type(parsed).__name__}")

# ================= N-02~05 list_metrics ×4 =================
for inst in ("sales", "restaurant", "retail", "hro"):
    ok, parsed, raw = mcp("list_metrics", {"instance": inst})
    save(f"metrics_list_{inst}.json", envelope(ok, raw, parsed))
    n = len(parsed) if isinstance(parsed, list) else "?"
    note(f"N-0X list_metrics {inst}", f"ok={ok} entries={n}")

# ================= N-26~29 list_reports ×4 =================
for inst in ("retail", "hro", "sales", "restaurant"):
    ok, parsed, raw = mcp("list_reports", {"instance": inst})
    save(f"list_reports_{inst}.json", envelope(ok, raw, parsed))
    n = len(parsed) if isinstance(parsed, list) else "?"
    note(f"N-2X list_reports {inst}", f"ok={ok} entries={n}")

# ================= N-06~11 retail 报表 ×6（无筛选全量） =================
P_REPORT = prop_for("query_report", "report", "key", default="report")
P_INSTANCE = prop_for("query_report", "instance", default="instance")
P_FILTERS = prop_for("query_report", "filter", default="filters")
P_LIMIT = prop_for("query_report", "limit", default="limit")
P_METRIC = prop_for("get_caliber", "metric", "name", default="metric")
note("N-00", f"adopted param names: report={P_REPORT} instance={P_INSTANCE} filters={P_FILTERS} limit={P_LIMIT} metric={P_METRIC}")

for key in ("monthly_kpi", "region_month", "category_month", "channel_month", "store_rank", "supplier_rank"):
    args = {P_REPORT: key, P_INSTANCE: "retail"}
    ok, parsed, raw = mcp("query_report", args)
    form = to_rows_form(parsed)
    save(f"report_rows_retail_{key}.json", form)
    nrow = len(form.get("rows") or [])
    note(f"N-06~11 retail/{key}", f"ok={ok} rows={nrow} cols={form.get('columns')}")

# ================= N-12~17 hro 报表 ×6 =================
for key in ("monthly_kpi", "bu_month", "group_rank", "customer_ar", "industry_month", "contract_ledger"):
    args = {P_REPORT: key, P_INSTANCE: "hro"}
    ok, parsed, raw = mcp("query_report", args)
    form = to_rows_form(parsed)
    save(f"report_rows_hro_{key}.json", form)
    nrow = len(form.get("rows") or [])
    note(f"N-12~17 hro/{key}", f"ok={ok} rows={nrow}")

# ================= N-18~20 筛选报表 ×3 =================
ok, parsed, raw = mcp("query_report", {P_REPORT: "region_month", P_INSTANCE: "retail", P_FILTERS: {"城市": "上海"}})
save("report_filtered_retail_region_month_cityshanghai.json", to_rows_form(parsed))
note("N-18", f"ok={ok} rows={len((to_rows_form(parsed).get('rows')) or [])}")

ok, parsed, raw = mcp("query_report", {P_REPORT: "channel_month", P_INSTANCE: "retail", P_FILTERS: {"渠道": "电商"}})
save("report_filtered_retail_channel_month_ecommerce.json", to_rows_form(parsed))
note("N-19", f"ok={ok} rows={len((to_rows_form(parsed).get('rows')) or [])}")

ok, parsed, raw = mcp("query_report", {P_REPORT: "industry_month", P_INSTANCE: "hro", P_FILTERS: {"行业": "互联网"}})
save("report_filtered_hro_industry_month_internet.json", to_rows_form(parsed))
note("N-20", f"ok={ok} rows={len((to_rows_form(parsed).get('rows')) or [])}")

# ================= N-21~24 get_data_status ×4 =================
for inst in ("restaurant", "sales", "retail", "hro"):
    ok, parsed, raw = mcp("get_data_status", {"instance": inst})
    save(f"status_{inst}.json", envelope(ok, raw, parsed))
    note(f"N-2X status {inst}", f"ok={ok} parsed={str(parsed)[:200]}")

# ================= N-25 get_caliber 六连 =================
# 从目录证据里自适应找指标标识符；找不到就用中文口径名直试。
def find_metric_id(inst, term):
    p = os.path.join(ACTUAL, f"metrics_list_{inst}.json")
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    entries = data.get("parsed") if isinstance(data, dict) else data
    ids = []
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict):
                for k in ("name", "key", "id", "metric"):
                    v = e.get(k)
                    if isinstance(v, str) and term in v:
                        ids.append(v)
                # 兜底：任意字符串值包含 term
                for v in e.values():
                    if isinstance(v, str) and term in v and v not in ids:
                        ids.append(v)
            elif isinstance(e, str) and term in e:
                ids.append(e)
    return ids


CALIBERS = [
    ("retail", "毛利率"),
    ("retail", "库存周转率"),
    ("hro", "回款率"),
    ("hro", "人均产值"),
    ("sales", "收入"),
    ("restaurant", "客单数"),
]
for inst, term in CALIBERS:
    candidates = [term] + [c for c in find_metric_id(inst, term) if c != term]
    tried = []
    done = False
    for cand in candidates:
        args = {"instance": inst, P_METRIC: cand}
        ok, parsed, raw = mcp("get_caliber", args)
        tried.append({"arg": cand, "ok": ok, "head": raw[:160]})
        if ok and parsed is not None and not (isinstance(parsed, dict) and parsed.get("error")):
            fname = f"caliber_{inst}_{cand}.json"
            save(fname, envelope(ok, raw, parsed, args_used=args, arg_attempts=tried))
            note(f"N-25 {inst}/{term}", f"resolved arg={cand} ok={ok}")
            done = True
            break
    if not done:
        save(f"caliber_{inst}_{term}.json", envelope(False, raw, parsed, args_used={"instance": inst, "metric": term}, arg_attempts=tried))
        note(f"N-25 {inst}/{term}", f"UNRESOLVED attempts={tried}")

# ================= N-30~34 HTTP 面 =================
st, parsed, body = http_get("/api/open/reports?instance=retail")
save("http_reports_retail.json", envelope(200 <= st < 300, body, parsed, http_status=st))
note("N-30", f"http_status={st}")

st, parsed, body = http_get("/api/open/reports/monthly_kpi/data?instance=retail")
save("http_report_data_retail_monthly_kpi.json", envelope(200 <= st < 300, body, parsed, http_status=st))
nrow = len((parsed or {}).get("rows") or (parsed or {}).get("data") or []) if isinstance(parsed, dict) else "?"
note("N-31", f"http_status={st} rows={nrow}")

st, parsed, body = http_get("/api/open/reports/contract_ledger/data?instance=hro")
save("http_report_data_hro_contract_ledger.json", envelope(200 <= st < 300, body, parsed, http_status=st))
nrow = len((parsed or {}).get("rows") or (parsed or {}).get("data") or []) if isinstance(parsed, dict) else "?"
note("N-32", f"http_status={st} rows={nrow}")

st, parsed, body = http_get("/api/open/metrics?instance=hro")
save("http_metrics_hro.json", envelope(200 <= st < 300, body, parsed, http_status=st))
note("N-33", f"http_status={st}")

st, parsed, body = http_get("/api/open/status?instance=restaurant")
save("http_status_restaurant.json", envelope(200 <= st < 300, body, parsed, http_status=st))
note("N-34", f"http_status={st} parsed={str(parsed)[:200]}")

# ================= B-01 未知账套 list_metrics =================
ok, parsed, raw = mcp("list_metrics", {"instance": "_no_such_instance__"})
save("b01_unknown_instance.json", envelope(ok, raw, parsed))
note("B-01", f"ok={ok} raw_head={raw[:200]}")

# ================= B-02 未知报表 =================
ok, parsed, raw = mcp("query_report", {P_REPORT: "_no_such_report__", P_INSTANCE: "retail"})
save("b02_unknown_report.json", envelope(ok, raw, parsed))
note("B-02", f"ok={ok} raw_head={raw[:200]}")

# ================= B-03 未知指标 =================
ok, parsed, raw = mcp("get_caliber", {"instance": "retail", P_METRIC: "_no_such_metric__"})
save("b03_unknown_metric.json", envelope(ok, raw, parsed))
note("B-03", f"ok={ok} raw_head={raw[:200]}")

# ================= B-04 未知筛选维度 =================
ok, parsed, raw = mcp("query_report", {P_REPORT: "region_month", P_INSTANCE: "retail", P_FILTERS: {"不存在的维度__": "任意值"}})
save("b04_unknown_filterdim.json", envelope(ok, raw, parsed))
note("B-04", f"ok={ok} raw_head={raw[:200]}")

# ================= B-05 MCP 注入 =================
INJ = "华东' OR 1=1--"
ok, parsed, raw = mcp("query_report", {P_REPORT: "region_month", P_INSTANCE: "retail", P_FILTERS: {"大区": INJ}})
form = to_rows_form(parsed)
save("b05_inject_mcp.json", envelope(ok, raw, parsed))
note("B-05", f"ok={ok} rows={len(form.get('rows') or [])} contains_inject_literal={'OR 1=1' in raw}")

# ================= B-06 HTTP 无钥匙 =================
st, parsed, body = http_get("/api/open/status?instance=retail", api_key=None)
save("b06_http_nokey.json", envelope(200 <= st < 300, body, parsed, http_status=st))
note("B-06", f"http_status={st}")

# ================= B-07 HTTP 坏钥匙 =================
st, parsed, body = http_get("/api/open/status?instance=retail", api_key="cl-invalid-key-for-test-000")
save("b07_http_badkey.json", envelope(200 <= st < 300, body, parsed, http_status=st))
note("B-07", f"http_status={st}")

# ================= B-08 HTTP 注入（两种参数风格 + openapi 观察项） =================
st_oapi, oapi_parsed, _ = http_get("/openapi.json")
declared_params = None
if isinstance(oapi_parsed, dict):
    try:
        declared_params = oapi_parsed["paths"]["/api/open/reports/{report_key}/data"].get("get", {}).get("parameters")
    except Exception:
        declared_params = f"openapi_status={st_oapi}, path not found"
attempts = []
for style, suffix in (("filter_style", "&filter=" + quote(f"大区:{INJ}")), ("bare_param_style", "&" + quote("大区") + "=" + quote(INJ))):
    path = "/api/open/reports/region_month/data?instance=retail" + suffix
    st, parsed, body = http_get(path)
    attempts.append({"style": style, "path_suffix": suffix, "http_status": st,
                     "body_contains_OR11": "OR 1=1" in body,
                     "rows": len((parsed or {}).get("rows") or (parsed or {}).get("data") or []) if isinstance(parsed, dict) else None,
                     "raw": body})
save("b08_inject_http.json", {"tool_or_endpoint": "GET /api/open/reports/region_month/data?instance=retail",
                              "args_or_path": {"injection_value": INJ}, "attempts": attempts,
                              "declared_params_openapi": declared_params,
                              "ok": all(a["http_status"] == 200 for a in attempts),
                              "http_status": attempts[0]["http_status"], "raw": attempts[0]["raw"], "parsed": None})
note("B-08", f"attempts={[(a['style'], a['http_status'], a['rows'], a['body_contains_OR11']) for a in attempts]} openapi_params={str(declared_params)[:300]}")

# ================= B-09 limit 边界三连 =================
ok, parsed, raw = mcp("query_report", {P_REPORT: "monthly_kpi", P_INSTANCE: "retail", P_LIMIT: 100000})
mcp_rows = len((to_rows_form(parsed).get("rows")) or []) if ok else None
st5, parsed5, body5 = http_get("/api/open/reports/monthly_kpi/data?instance=retail&limit=5")
rows5 = len((parsed5 or {}).get("rows") or (parsed5 or {}).get("data") or []) if isinstance(parsed5, dict) else None
stabc, parsedabc, bodyabc = http_get("/api/open/reports/monthly_kpi/data?instance=retail&limit=abc")
save("b09_limit.json", {"tool_or_endpoint": "query_report + HTTP monthly_kpi/data",
                        "mcp_limit_100000": {"ok": ok, "rows": mcp_rows, "raw_head": raw[:200]},
                        "http_limit_5": {"http_status": st5, "rows": rows5, "raw": body5},
                        "http_limit_abc": {"http_status": stabc, "raw_head": bodyabc[:300]},
                        "ok": ok and 200 <= st5 < 300, "raw": raw, "parsed": None,
                        "http_status": st5})
note("B-09", f"mcp(100000): ok={ok} rows={mcp_rows}; http limit=5: {st5} rows={rows5}; http limit=abc: {stabc}")

# ================= B-10 下划线探针账套 =================
probe_dir = os.path.join(ROOT, "instances", "_probe_openapi_tmp")
probe_created = False
cleanup_done = False
try:
    os.makedirs(probe_dir, exist_ok=True)
    with open(os.path.join(probe_dir, "instance.yml"), "w", encoding="utf-8") as f:
        f.write("name: _probe_openapi_tmp\ntitle: 探测副本\n")
    probe_created = os.path.isfile(os.path.join(probe_dir, "instance.yml"))
    ok, parsed, raw = mcp("list_instances", {})
    b10_parsed = parsed
    b10_raw = raw
    b10_ok = ok
finally:
    if os.path.isdir(probe_dir):
        shutil.rmtree(probe_dir, ignore_errors=True)
        cleanup_done = not os.path.exists(probe_dir)
save("b10_underscore.json", {"tool_or_endpoint": "list_instances", "args_or_path": {"probe_instance_yml": "name: _probe_openapi_tmp / title: 探测副本"},
                             "probe_created": probe_created, "cleanup_done": cleanup_done,
                             "ok": b10_ok, "raw": b10_raw, "parsed": b10_parsed, "http_status": None})
note("B-10", f"probe_created={probe_created} cleanup_done={cleanup_done} ok={b10_ok} entries={len(b10_parsed) if isinstance(b10_parsed, list) else '?'}")

# ================= B-11 审计日志行数 =================
audit_path = os.path.join(ROOT, "logs", "mcp_audit.jsonl")


def count_lines(p):
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)


before = count_lines(audit_path)
ok, parsed, raw = mcp("list_instances", {})
after = count_lines(audit_path)
valid = True
bad_lines = []
if after:
    with open(audit_path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except Exception:
                valid = False
                bad_lines.append(i)
save("b11_audit.json", {"tool_or_endpoint": "list_instances", "args_or_path": {},
                        "lines_before": before, "lines_after": after,
                        "grew": (after or 0) > (before or 0),
                        "all_lines_valid_json": valid, "invalid_line_numbers": bad_lines,
                        "ok": ok, "raw": raw, "parsed": parsed, "http_status": None})
note("B-11", f"before={before} after={after} valid_json={valid} bad={bad_lines}")

# ================= B-12 未知账套 get_data_status =================
ok, parsed, raw = mcp("get_data_status", {"instance": "_no_such_instance__"})
save("b12_unknown_instance_status.json", envelope(ok, raw, parsed))
note("B-12", f"ok={ok} raw_head={raw[:200]}")

# ================= 收尾：采集日志 =================
with open(os.path.join(ROOT, "tests", "v0.5", "judge", "collect_round1_log.json"), "w", encoding="utf-8") as f:
    json.dump(LOG, f, ensure_ascii=False, indent=2)
print("COLLECT DONE (B-13 请单独最后执行)")
