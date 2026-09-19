# -*- coding: utf-8 -*-
"""明账 ClearLedger — 门户后端（v0.3 实例化版）

账套模型：settings.instance 指向当前公司账套，全部数据 API 按账套路由到
instances/<n>/（五配置）与 data/warehouse/<n>.duckdb（独立库）。旧手写管道已退役。
启动：.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8620
"""
from __future__ import annotations

import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import duckdb
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semantic import query as semantic_query
from semantic.loader import ConfigError, list_instances, load_instance

from app import config
from app.services import dbt_runner, settings as settings_svc
from app.services.export import to_xlsx

# ---------------------------------------------------------------- 调度器
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _scheduled_build() -> None:
    inst = settings_svc.load().get("instance", "sales")
    dbt_runner.trigger_run(inst, "schedule")


def _apply_schedule() -> dict:
    s = settings_svc.load()
    if s["schedule_enabled"]:
        scheduler.add_job(
            _scheduled_build, "cron",
            hour=s["schedule_hour"], minute=s["schedule_minute"],
            id="daily_build", replace_existing=True,
            misfire_grace_time=3600 * 6,
            coalesce=True,
        )
    else:
        try:
            scheduler.remove_job("daily_build")
        except Exception:
            pass
    return s


def _schedule_info() -> dict:
    s = settings_svc.load()
    s["label"] = ("每天 {:02d}:{:02d}".format(s["schedule_hour"], s["schedule_minute"])
                  if s["schedule_enabled"] else "手动模式")
    s["next_run_time"] = None
    try:
        job = scheduler.get_job("daily_build")
        if job is not None and job.next_run_time is not None:
            s["next_run_time"] = job.next_run_time.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return s


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    _apply_schedule()
    # 定时模式下的启动补跑（>24h 断档）；手动模式绝不自动跑（决策 D5/D11）
    try:
        s = settings_svc.load()
        runs = dbt_runner.history(s["instance"])
        stale = not runs or datetime.fromisoformat(runs[0]["finished_at"]) < datetime.now() - timedelta(hours=24)
        if s["schedule_enabled"] and stale and not dbt_runner.status()["active"]:
            dbt_runner.trigger_run(s["instance"], "catchup")
    except Exception:
        pass
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def no_cache_html(request, call_next):
    """根治缓存事故：入口 html 禁缓存（否则升级后浏览器拿旧 index.html 引旧 JS，
    与新 API 字段错位导致页面空白——真实踩坑）；带版本号的 js/css 仍可长缓存"""
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if "text/html" in ct:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        # 客户端参数非法（如筛选维度名不存在）→ 4xx，不得伪装"服务端不可用"
        raise HTTPException(400, f"请求参数非法：{e}")
    except (FileNotFoundError, RuntimeError, ConfigError, duckdb.Error) as e:
        raise HTTPException(503, f"数据暂不可用（可能正在跑批或尚未初始化）：{e}")


def _inst() -> str:
    return settings_svc.load().get("instance", "sales")


def _stale_info() -> tuple[bool, str | None]:
    run = dbt_runner.latest_run(_inst())
    if run and run.get("status") == "red":
        return True, f"账套[{_inst()}] 最近一次跑批失败（{run.get('finished_at', '')}），以下为最近一次成功跑批的旧数据"
    return False, None


# ---------------------------------------------------------------- 账套
@app.get("/api/instance")
def api_instance_get():
    s = settings_svc.load()
    instances = []
    for n in list_instances():
        inst = load_instance(n)
        run = dbt_runner.latest_run(n)
        instances.append({
            "name": n, "title": inst.title,
            "status": (run or {}).get("status", "unknown"),
            "last_run": (run or {}).get("finished_at"),
        })
    cur = next((i for i in instances if i["name"] == s["instance"]), None)
    return {"current": s["instance"], "current_title": cur["title"] if cur else s["instance"],
            "instances": instances}


@app.post("/api/instance")
def api_instance_switch(payload: dict = Body(...)):
    name = payload.get("instance")
    if not name or name not in list_instances():
        raise HTTPException(404, f"账套不存在：{name}（可用: {list_instances()}）")
    settings_svc.save({"instance": name})
    return {"current": name, "message": f"已切换到账套 {name}"}


# ---------------------------------------------------------------- 总览
_STATUS_TO_LIGHT = {
    "success": "green", "pass": "green", "warn": "yellow",
    "error": "red", "fail": "red", "runtime error": "red",
    "skipped": "unknown", "not_run": "unknown",
}


@app.get("/api/overview")
def api_overview():
    name = _inst()
    run = dbt_runner.latest_run(name)

    # KPI：当前账套的月度报表（monthly_kpi）最新完整月 + 前月
    kpi_rows = _guard(semantic_query.run_report, name, "monthly_kpi", None, 200) \
        if any(r["key"] == "monthly_kpi" for r in semantic_query.list_reports(name)) else []
    latest = kpi_rows[-1] if kpi_rows else None
    prev = kpi_rows[-2] if len(kpi_rows) > 1 else None

    warns = []
    if run:
        for uid, n in run.get("nodes", {}).items():
            if uid.startswith("test.") and n.get("status") == "warn":
                warns.append({"uid": uid, "name": uid.split(".")[-1],
                              "message": n.get("message"), "failures": n.get("failures")})

    return {
        "app": {"name": config.APP_NAME, "version": config.APP_VERSION},
        "instance": {"name": name, "title": next(
            (i["title"] for i in api_instance_get()["instances"] if i["name"] == name), name)},
        "light": run["status"] if run else "unknown",
        "last_run": None if not run else {
            "run_id": run["run_id"], "trigger": run["trigger"],
            "started_at": run["started_at"], "finished_at": run["finished_at"],
            "status": run["status"], "counts": run.get("counts", {}),
        },
        "running": dbt_runner.status(),
        "schedule": _schedule_info(),
        "kpi": {"latest": latest, "prev": prev},
        "trend": kpi_rows,
        "warnings": warns,
    }


# ---------------------------------------------------------------- 血缘
@app.get("/api/lineage/graph")
def api_lineage_graph():
    name = _inst()
    try:
        inst = load_instance(name)
    except ConfigError as e:
        raise HTTPException(503, str(e))
    run = dbt_runner.latest_run(name)
    status_by_uid = (run or {}).get("nodes", {})
    ingest_by_source = {}
    if run and run.get("ingest"):
        for r in run["ingest"].get("results", []):
            ingest_by_source[r.get("source")] = r.get("status")

    nodes, edges = [], []
    wide = inst.wide.get("wide", {})
    wide_name = wide.get("name")
    main = wide.get("main")
    # 源节点
    for src in inst.sources.get("sources", []):
        st = "unknown"
        if src["name"] in ingest_by_source:
            st = "green" if ingest_by_source[src["name"]] == "ok" else "red"
        nodes.append({"uid": f"source.raw.{src['name']}", "name": src["name"],
                      "resource_type": "source", "schema": "raw",
                      "description": src.get("title", ""), "column_count": 0,
                      "test_count": 0, "tags": [], "status": st})
    # 宽表 + 报表节点（来自 manifest 的真实依赖）
    manifest_path = inst.pipeline_dir / "target" / "manifest.json"
    if manifest_path.exists():
        import json
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        for uid, n in {**m.get("nodes", {}), **m.get("sources", {})}.items():
            rt = n.get("resource_type")
            if rt not in ("model", "seed", "snapshot"):
                continue
            st = (status_by_uid.get(uid, {}) or {}).get("status")
            nodes.append({
                "uid": uid, "name": n.get("name"), "resource_type": rt,
                "schema": n.get("schema"),
                "description": (n.get("description") or "").strip(),
                "column_count": len(n.get("columns") or {}),
                "test_count": 0, "tags": n.get("tags") or [],
                "status": _STATUS_TO_LIGHT.get(st, "unknown") if st else "unknown",
            })
            for dep in (n.get("depends_on") or {}).get("nodes", []):
                edges.append({"source": dep, "target": uid})
    else:
        # 未编译过：至少给出配置级骨架
        nodes.append({"uid": f"model.{wide_name}", "name": wide_name, "resource_type": "model",
                      "schema": "intermediate", "description": "宽表（尚未编译）",
                      "column_count": 0, "test_count": 0, "tags": [], "status": "unknown"})
    # 过滤孤立节点（血缘图只留有边或被边引用的；load_log 类孤立源由 ingest_by_source 着色保留）
    linked = {e["source"] for e in edges} | {e["target"] for e in edges}
    nodes = [n for n in nodes if n["uid"] in linked or n["resource_type"] == "source"]
    return {"nodes": nodes, "edges": edges, "generated_at": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/lineage/columns/{name}")
def api_lineage_columns(name: str):
    name_ = _inst()
    manifest_path = load_instance(name_).pipeline_dir / "target" / "manifest.json"
    import json
    if not manifest_path.exists():
        return {"model": name, "available": False, "reason": "暂无编译产物（先跑一次批）", "columns": []}
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    node = next((n for n in m.get("nodes", {}).values()
                 if n.get("name") == name and n.get("resource_type") == "model"), None)
    if node is None:
        return {"model": name, "available": False, "reason": "模型不存在", "columns": []}
    sql = node.get("compiled_code")
    if not sql:
        return {"model": name, "available": False, "reason": "暂无编译后 SQL", "columns": []}
    import re as _re
    upstream = []
    for dep in (node.get("depends_on") or {}).get("nodes", []):
        parts = dep.split(".")
        upstream.append(parts[-1] if len(parts) >= 3 else dep)
    # 标识符启发式：列 ← 提及的上游表
    cols_out = []
    for col, meta in (node.get("columns") or {}).items():
        cols_out.append({"column": col, "description": (meta.get("description") or "").strip(),
                         "upstreams": [], "ok": True})
    # 用 SQLGlot 做真实字段级血缘（与 pipeline 无关，纯解析）
    try:
        import sqlglot
        from sqlglot.lineage import lineage as sg
        simplified = sql = node.get("compiled_code") or ""
        for u in sorted(set(upstream), key=len, reverse=True):
            pattern = rf'(?:"?[\w]+"?\.)+"?{ _re.escape(u) }"?(?![\w])'
            simplified = _re.sub(pattern, u, simplified)
        schema_map = {}
        for dep_uid, dn in {**m.get("nodes", {}), **m.get("sources", {})}.items():
            if dn.get("name") in upstream:
                schema_map[dn["name"]] = {c: "UNKNOWN" for c in (dn.get("columns") or {})}
        for entry in cols_out:
            try:
                root = sg(entry["column"], simplified, schema=schema_map, dialect="duckdb")
                seen = set()
                for nd in root.walk():
                    src = getattr(nd, "source", None)
                    if isinstance(src, sqlglot.exp.Table):
                        tbl = src.name
                        rawname = str(getattr(nd, "name", ""))
                        cp = rawname.split(":", 1)[0].strip()
                        if "." in cp:
                            cp = cp.rsplit(".", 1)[-1]
                        if ":" in rawname or cp in ("", "*"):
                            cp = "*"
                        if (tbl, cp) == (name, entry["column"]):
                            continue
                        if (tbl, cp) not in seen:
                            seen.add((tbl, cp))
                            entry["upstreams"].append({"table": tbl, "column": cp})
            except Exception:
                entry["ok"] = False
    except Exception:
        pass
    return {"model": name, "available": True, "columns": cols_out}


@app.get("/api/node/{uid}")
def api_node_detail(uid: str):
    name_ = _inst()
    manifest_path = load_instance(name_).pipeline_dir / "target" / "manifest.json"
    import json
    if not manifest_path.exists():
        raise HTTPException(404, "暂无编译产物")
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    node = {**m.get("nodes", {}), **m.get("sources", {})}.get(uid)
    if node is None:
        raise HTTPException(404, "节点不存在")
    run = dbt_runner.latest_run(name_)
    st = (run or {}).get("nodes", {}).get(uid, {})
    cols = [{"name": c, "type": None, "description": (meta.get("description") or "").strip()}
            for c, meta in (node.get("columns") or {}).items()]
    tests = [{"uid": t_uid, "name": t_name, "kind": "自定义",
              "severity": ((t_cfg or {}).get("severity")) or "error"}
             for t_uid, t_node in m.get("nodes", {}).items()
             if t_node.get("resource_type") == "test"
             for t_cfg in [t_node.get("config")]
             if ((t_node.get("depends_on") or {}).get("nodes") or [None])[0] == uid
             for t_name in [t_node.get("name")]]
    return {"uid": uid, "name": node.get("name"), "resource_type": node.get("resource_type"),
            "schema": node.get("schema"), "description": (node.get("description") or "").strip(),
            "tags": node.get("tags") or [], "path": node.get("original_file_path"),
            "columns": cols, "tests": tests,
            "status": st.get("status", "unknown"), "last_message": st.get("message"),
            "last_time": st.get("time")}


# ---------------------------------------------------------------- 数据字典
@app.get("/api/dictionary")
def api_dictionary():
    name_ = _inst()
    try:
        inst = load_instance(name_)
    except ConfigError as e:
        raise HTTPException(503, str(e))
    manifest_path = inst.pipeline_dir / "target" / "manifest.json"
    import json
    m = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"nodes": {}, "sources": {}}

    type_map: dict[tuple, dict] = {}
    try:
        rows = duckdb.connect(str((inst.pipeline_dir / inst.db_path).resolve()), read_only=True).execute(
            "select table_schema, table_name, column_name, data_type from information_schema.columns "
            "where table_schema in ('raw','staging','intermediate','marts')"
        ).fetchall()
        for s_, t_, c_, d_ in rows:
            type_map.setdefault((s_, t_), {})[c_] = d_
    except Exception:
        pass

    tables: list[dict] = []
    for uid, n in {**m.get("nodes", {}), **m.get("sources", {})}.items():
        if n.get("resource_type") not in ("model", "source"):
            continue
        ct = type_map.get((n.get("schema"), n.get("name")), {})
        tables.append({
            "uid": uid, "schema": n.get("schema"), "name": n.get("name"),
            "kind": n.get("resource_type"),
            "description": (n.get("description") or "").strip(),
            "test_count": sum(1 for t in m.get("nodes", {}).values()
                              if t.get("resource_type") == "test"
                              and ((t.get("depends_on") or {}).get("nodes") or [None])[0] == uid),
            "columns": [{"name": c, "type": ct.get(c),
                         "description": (meta.get("description") or "").strip()}
                        for c, meta in (n.get("columns") or {}).items()],
        })
    tables.sort(key=lambda t: ({"source": 0, "model": 1}.get(t["kind"], 2), t["schema"] or "", t["name"]))
    return {"tables": tables, "generated_at": datetime.now().isoformat(timespec="seconds")}


# ---------------------------------------------------------------- 报表（语义层驱动）
@app.get("/api/reports")
def api_reports():
    name = _inst()
    reports = semantic_query.list_reports(name)
    out = []
    for r in reports:
        out.append({
            "key": r["key"], "title": r["title"], "description": r["title"],
            "dimension": r["dimension"], "time_dim": r.get("time_dim"),
            "metrics": r.get("metrics", []),
            "params": ([{"name": r["dimension"], "label": r["dimension"], "type": "select",
                         "options_from": r["dimension"], "default": ""}] +
                       [{"name": f, "label": f, "type": "select", "options_from": f, "default": ""}
                        for f in (r.get("filters") or [])]),
        })
    return {"reports": out, "options": _all_options(name)}

def _all_options(instance: str) -> dict:
    opts: dict[str, list] = {}
    for r in semantic_query.list_reports(instance):
        try:
            for k, v in semantic_query.filter_options(instance, r["key"]).items():
                opts.setdefault(k, [])
                for v_ in v:
                    if v_ not in opts[k]:
                        opts[k].append(v_)
        except Exception:
            pass
    return opts


@app.get("/api/reports/{key}/data")
def api_report_data(key: str, request: Request, limit: int | None = None):
    try:
        rep = next(r for r in semantic_query.list_reports(_inst()) if r["key"] == key)
    except StopIteration:
        raise HTTPException(404, f"报表不存在：{key}")
    allowed = set(semantic_query.filter_options(_inst(), key).keys())
    filters = {k: v for k, v in request.query_params.items() if k in allowed}
    rows = _guard(semantic_query.run_report, _inst(), key, filters, limit or 500)
    cols = [(rep["dimension"], rep["dimension"])] + (
        [(rep["time_dim"], rep["time_dim"])] if rep.get("time_dim") else [])
    seen = {c for _, c in cols}
    if rows:
        for k in rows[0]:
            if k not in seen:
                cols.append((k, k))
    stale, info = _stale_info()
    return {"key": key, "title": rep["title"], "columns": cols, "rows": rows,
            "stale": stale, "stale_info": info}


@app.get("/api/reports/{key}/export")
def api_report_export(key: str, request: Request, limit: int | None = None):
    try:
        rep = next(r for r in semantic_query.list_reports(_inst()) if r["key"] == key)
    except StopIteration:
        raise HTTPException(404, f"报表不存在：{key}")
    allowed = set(semantic_query.filter_options(_inst(), key).keys())
    filters = {k: v for k, v in request.query_params.items() if k in allowed}
    rows = _guard(semantic_query.run_report, _inst(), key, filters, limit or 5000)
    cols = [(rep["dimension"], rep["dimension"])] + (
        [(rep["time_dim"], rep["time_dim"])] if rep.get("time_dim") else [])
    if rows:
        for k in rows[0]:
            if all(k != c for c, _ in cols):
                cols.append((k, k))
    stale, info = _stale_info()
    content = to_xlsx(cols, rows, sheet=rep["title"], note=info)
    filename = f"{rep['title']}_{datetime.now():%Y%m%d}.xlsx"
    return Response(content=content,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


# ---------------------------------------------------------------- 口径（界面展示）
@app.get("/api/caliber")
def api_caliber():
    """当前账套的指标/派生列/维度口径——报表页「📐 口径」弹窗的数据源。
    口径唯一出处：instances/<账套>/metrics.yml 与 wide.yml（本端点只读展示）"""
    try:
        inst = load_instance(_inst())
    except ConfigError as e:
        raise HTTPException(503, str(e))
    wide = inst.wide.get("wide", {})
    return {
        "instance": {"name": inst.name, "title": inst.title},
        "metrics": [{"name": m["name"], "expr": m.get("expr", ""),
                     "desc": m.get("desc", ""), "format": m.get("format")}
                    for m in inst.metrics],
        "derived": [{"name": d["name"], "expr": d.get("expr", ""),
                     "desc": d.get("desc", "")}
                    for d in wide.get("derived", [])],
        "dimensions": [{"name": d["name"], "column": d.get("column"),
                        "type": d.get("type")}
                       for d in inst.dimensions],
    }


# ---------------------------------------------------------------- 设置
@app.get("/api/settings")
def api_settings_get():
    return _schedule_info()


@app.post("/api/settings")
def api_settings_patch(payload: dict = Body(...)):
    patch = {}
    if "schedule_enabled" in payload:
        patch["schedule_enabled"] = bool(payload["schedule_enabled"])
    try:
        if "hour" in payload:
            patch["schedule_hour"] = int(payload["hour"])
        if "minute" in payload:
            patch["schedule_minute"] = int(payload["minute"])
    except (TypeError, ValueError):
        raise HTTPException(422, "时间格式不对")
    settings_svc.save(patch)
    _apply_schedule()
    return _schedule_info()

# ---------------------------------------------------------------- 跑批
@app.get("/api/runs")
def api_runs(instance: str | None = None):
    runs = dbt_runner.history(instance) if instance else dbt_runner.all_history()
    return {"runs": [
        {k: r.get(k) for k in ("run_id", "instance", "trigger", "started_at",
                               "finished_at", "status", "counts")}
        for r in runs
    ]}


@app.get("/api/runs/status")
def api_run_status():
    return dbt_runner.status()


@app.post("/api/runs/trigger")
def api_run_trigger(instance: str | None = None):
    inst = instance or _inst()
    run_id = dbt_runner.trigger_run(inst, "manual")
    if run_id is None:
        raise HTTPException(409, "已有跑批在进行中")
    return {"run_id": run_id, "instance": inst, "message": f"账套[{inst}] 跑批已启动"}


@app.get("/api/runs/{run_id}")
def api_run_detail(run_id: str):
    run = next((r for r in dbt_runner.all_history() if r["run_id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "运行记录不存在")
    manifest_uids: dict[str, dict] = {}
    try:
        inst = load_instance(run.get("instance") or _inst())
        mp = inst.pipeline_dir / "target" / "manifest.json"
        if mp.exists():
            import json as _json
            mm = _json.loads(mp.read_text(encoding="utf-8"))
            manifest_uids = {uid: n.get("name", uid) for uid, n in mm.get("nodes", {}).items()}
    except Exception:
        pass

    def _row(uid: str, n: dict):
        return {"uid": uid, "name": manifest_uids.get(uid, uid.split(".")[-1] if uid else uid),
                "kind": "model" if uid.startswith("model.") else ("test" if uid.startswith("test.") else "?"),
                "status": n.get("status"), "time": n.get("time"), "message": n.get("message")}

    nodes = [_row(uid, n) for uid, n in run.get("nodes", {}).items()]
    nodes.sort(key=lambda r: (0 if r["kind"] == "model" else 1, r["name"]))
    return {**{k: run.get(k) for k in ("run_id", "instance", "trigger", "started_at", "finished_at",
                                       "status", "ingest_ok", "ingest", "counts", "error", "dbt_returncode")},
            "nodes": nodes}


@app.get("/api/runs/{run_id}/log")
def api_run_log(run_id: str, tail: int = 300):
    run = next((r for r in dbt_runner.all_history() if r["run_id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "运行记录不存在")
    log_file = Path(run.get("log_file", ""))
    if not log_file.exists():
        return PlainTextResponse("(无日志)")
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return PlainTextResponse("\n".join(lines[-max(10, min(tail, 2000)):]))

# ---------------------------------------------------------------- 开放接口（agent 用，钥匙鉴权）
def _check_key(request: Request) -> str:
    """开放接口鉴权：X-API-Key ↔ principal（权限底座先行版）。审计留痕由各端点负责。"""
    keys_file = config.DATA_DIR / "openapi_keys.json"
    if not keys_file.exists():
        raise HTTPException(503, "开放接口未启用（缺少 data/openapi_keys.json）")
    try:
        keys = json.loads(keys_file.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(503, "openapi_keys.json 损坏")
    key = request.headers.get("X-API-Key", "")
    for k, meta in keys.items():
        if k == key:
            return meta.get("principal", "unknown")
    _audit_open(request, None, False)
    raise HTTPException(401, "无效的 API Key")


def _audit_open(request: Request, principal: str | None, ok: bool, detail: str = "") -> None:
    try:
        (config.LOG_DIR).mkdir(parents=True, exist_ok=True)
        with open(config.LOG_DIR / "open_api_audit.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                                "path": request.url.path, "principal": principal,
                                "ok": ok, "detail": detail[:120]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _open_instance(request: Request, name: str | None):
    principal = _check_key(request)
    _audit_open(request, principal, True, f"instance={name}")
    inst_name = name or settings_svc.load().get("instance", "sales")
    if inst_name not in list_instances():
        raise HTTPException(404, f"账套不存在：{inst_name}")
    return principal, inst_name


@app.get("/api/open/reports")
def api_open_reports(request: Request, instance: str | None = None):
    principal, inst_name = _open_instance(request, instance)
    return {"principal": principal, "reports": semantic_query.list_reports(inst_name)}


@app.get("/api/open/metrics")
def api_open_metrics(request: Request, instance: str | None = None):
    principal, inst_name = _open_instance(request, instance)
    inst = load_instance(inst_name)
    return {"principal": principal, "metrics": [
        {"name": m["name"], "expr": m.get("expr"), "desc": m.get("desc")} for m in inst.metrics]}


@app.get("/api/open/reports/{key}/data")
def api_open_report_data(key: str, request: Request, limit: int | None = None, instance: str | None = None):
    principal, inst_name = _open_instance(request, instance)
    try:
        rep = next(r for r in semantic_query.list_reports(inst_name) if r["key"] == key)
    except StopIteration:
        raise HTTPException(404, f"报表不存在：{key}")
    allowed = set(semantic_query.filter_options(inst_name, key).keys())
    filters = {k: v for k, v in request.query_params.items() if k in allowed}
    rows = _guard(semantic_query.run_report, inst_name, key, filters, limit or 200)
    _audit_open(request, principal, True, f"report={key} rows={len(rows)}")
    return {"instance": inst_name, "key": key, "rows": rows}


@app.get("/api/open/status")
def api_open_status(request: Request, instance: str | None = None):
    principal, inst_name = _open_instance(request, instance)
    run = dbt_runner.latest_run(inst_name)
    missing = []
    try:
        inst = load_instance(inst_name)
        for src in inst.sources.get("sources", []):
            if not any(any(inst.inbox.glob(pat)) for pat in
                       src.get("discover", {}).get("patterns", [f"{src['name']}.*"])):
                missing.append(src["name"])
    except Exception:
        pass
    out = {"instance": inst_name,
           "last_run": {k: (run or {}).get(k) for k in ("run_id", "status", "finished_at", "error")},
           "missing_files": missing}
    _audit_open(request, principal, True, f"status={out['last_run'].get('status')}")
    return out

# ---------------------------------------------------------------- 前端静态页
app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
