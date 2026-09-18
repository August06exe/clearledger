# -*- coding: utf-8 -*-
"""明账 ClearLedger — 门户后端

启动：.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8620
（前端静态页由本服务直接托管，浏览器访问 http://127.0.0.1:8620）
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import duckdb
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from app import config
from app.services import artifacts, dbt_runner, duck, export, lineage, reports
from app.services import settings as settings_svc

# ---------------------------------------------------------------- 调度器
scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _scheduled_build() -> None:
    dbt_runner.trigger_run("schedule")


def _apply_schedule() -> dict:
    """按设置应用定时任务：开关关闭时彻底移除定时任务，门户回到纯手动模式"""
    s = settings_svc.load()
    if s["schedule_enabled"]:
        scheduler.add_job(
            _scheduled_build, "cron",
            hour=s["schedule_hour"], minute=s["schedule_minute"],
            id="daily_build", replace_existing=True,
            misfire_grace_time=3600 * 6,  # 定时模式下，关机/睡眠错过 6 小时内醒来仍补跑
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
    # 启动补跑：仅在定时模式开启时生效——完全手动模式下，跑不跑由用户决定
    try:
        s = settings_svc.load()
        runs = dbt_runner.history()
        stale = not runs or datetime.fromisoformat(runs[0]["finished_at"]) < datetime.now() - timedelta(hours=24)
        if s["schedule_enabled"] and stale and not dbt_runner.status()["active"]:
            dbt_runner.trigger_run("catchup")
    except Exception:
        pass
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)


def _guard(fn, *args, **kwargs):
    """仓库不可用/正被占用/表结构未就绪时统一转 503，前端给出友好提示"""
    try:
        return fn(*args, **kwargs)
    except (FileNotFoundError, RuntimeError, duckdb.Error) as e:
        raise HTTPException(503, f"数据仓库暂不可用（可能正在跑批或尚未初始化）：{e}")


# ---------------------------------------------------------------- 总览
@app.get("/api/overview")
def api_overview():
    idx = artifacts.node_index()
    run = dbt_runner.latest_run()

    kpi_rows = _guard(
        duck.query_dicts,
        """
        select * from (
            select * from marts.mart_kpi_monthly
            where month < date_trunc('month', current_date)
            order by month desc limit 13
        ) order by month
        """,
    )
    latest = kpi_rows[-1] if kpi_rows else None
    prev = kpi_rows[-2] if len(kpi_rows) > 1 else None

    # 最新一轮跑批里的告警测试明细
    warns = []
    if run:
        for uid, n in run.get("nodes", {}).items():
            if uid.startswith("test.") and n.get("status") == "warn":
                meta = idx["nodes"].get(uid, {})
                warns.append({
                    "uid": uid, "name": meta.get("name", uid),
                    "message": n.get("message"), "failures": n.get("failures"),
                })

    by_type: dict[str, int] = {}
    for n in idx["nodes"].values():
        by_type[n["resource_type"]] = by_type.get(n["resource_type"], 0) + 1

    return {
        "app": {"name": config.APP_NAME, "version": config.APP_VERSION},
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
        "node_counts": by_type,
        "warnings": warns,
    }


# ---------------------------------------------------------------- 血缘
# 节点状态 → 灯色词汇（血缘图/管道 chips 统一用绿黄红表达）
_STATUS_TO_LIGHT = {
    "success": "green", "pass": "green",
    "warn": "yellow",
    "error": "red", "fail": "red", "runtime error": "red",
    "skipped": "unknown", "not_run": "unknown",
}


@app.get("/api/lineage/graph")
def api_lineage_graph():
    g = lineage.graph()
    run = dbt_runner.latest_run()
    status_by_uid = (run or {}).get("nodes", {})
    # 源表节点不参与 dbt 执行，用摄取结果着色（绿=成功入库 / 红=摄取失败）
    ingest_by_source: dict[str, str] = {}
    if run and run.get("ingest"):
        for r in run["ingest"].get("results", []):
            ingest_by_source[r.get("source")] = r.get("status")
    for n in g["nodes"]:
        st = status_by_uid.get(n["uid"], {}).get("status")
        if st:
            n["status"] = _STATUS_TO_LIGHT.get(st, "unknown")
        elif n["resource_type"] == "source" and ingest_by_source:
            n["status"] = "green" if ingest_by_source.get(n["name"]) == "ok" else "red"
        else:
            n["status"] = "unknown"
    return g


@app.get("/api/lineage/columns/{name}")
def api_lineage_columns(name: str):
    return lineage.column_lineage(name)


@app.get("/api/node/{uid}")
def api_node_detail(uid: str):
    idx = artifacts.node_index()
    node = idx["nodes"].get(uid)
    if node is None:
        raise HTTPException(404, "节点不存在")
    run = dbt_runner.latest_run()
    st = (run or {}).get("nodes", {}).get(uid, {})
    # 补充实时列类型
    types: dict[str, str] = {}
    if node["resource_type"] in ("model", "source"):
        try:
            rows = duck.query_dicts(
                "select column_name, data_type from information_schema.columns "
                "where table_schema = ? and table_name = ?",
                [node["schema"], node["name"]],
            )
            types = {r["column_name"]: r["data_type"] for r in rows}
        except Exception:
            types = {}
    cols = []
    for c, meta in node["columns"].items():
        cols.append({"name": c, "description": meta.get("description"), "type": types.get(c)})
    return {**{k: node[k] for k in ("uid", "name", "resource_type", "schema", "description", "tags", "path")},
            "columns": cols, "tests": node["tests"],
            "status": st.get("status", "unknown"), "last_message": st.get("message"),
            "last_time": st.get("time")}


# ---------------------------------------------------------------- 数据字典
@app.get("/api/dictionary")
def api_dictionary():
    idx = artifacts.node_index()
    type_map: dict[tuple[str, str], dict[str, str]] = {}
    try:
        rows = duck.query_dicts(
            "select table_schema, table_name, column_name, data_type "
            "from information_schema.columns "
            "where table_schema in ('raw','staging','intermediate','marts')"
        )
        for r in rows:
            key = (r["table_schema"], r["table_name"])
            type_map.setdefault(key, {})[r["column_name"]] = r["data_type"]
    except Exception:
        rows = []

    tables: list[dict] = []
    for uid, n in idx["nodes"].items():
        col_types = type_map.get((n["schema"], n["name"]), {})
        tables.append({
            "uid": uid,
            "schema": n["schema"],
            "name": n["name"],
            "kind": n["resource_type"],
            "description": n["description"],
            "test_count": len(n["tests"]),
            "columns": [
                {"name": c, "type": col_types.get(c), "description": m.get("description")}
                for c, m in n["columns"].items()
            ],
        })
    # raw.load_log（摄取日志）不在 manifest sources 里，手动补上
    try:
        log_cols = duck.query_dicts(
            "select column_name, data_type from information_schema.columns "
            "where table_schema='raw' and table_name='load_log'"
        )
        if log_cols:
            tables.append({
                "uid": "raw.load_log", "schema": "raw", "name": "load_log", "kind": "log",
                "description": "摄取日志：每个源文件每次入库的行数与时间，数据来龙去脉的第一环",
                "test_count": 0,
                "columns": [{"name": r["column_name"], "type": r["data_type"], "description": ""} for r in log_cols],
            })
    except Exception:
        pass
    tables.sort(key=lambda t: ({"source": 0, "model": 1}.get(t["kind"], 2), t["schema"], t["name"]))
    return {"tables": tables, "generated_at": datetime.now().isoformat(timespec="seconds")}


# ---------------------------------------------------------------- 报表
@app.get("/api/reports")
def api_reports():
    return {"reports": reports.list_reports(), "options": reports.report_options()}


def _stale_info() -> tuple[bool, str | None]:
    """红灯 = 最新数据未被本轮确认，报表应明确告知"这是旧数" """
    run = dbt_runner.latest_run()
    if run and run.get("status") == "red":
        return True, f"最近一次跑批失败（{run.get('finished_at', '')}），以下为最近一次成功跑批的旧数据"
    return False, None


@app.get("/api/reports/{key}/data")
def api_report_data(key: str, months: int | None = None, region: str | None = None,
                    level: str | None = None, category: str | None = None, limit: int | None = None):
    try:
        rep = reports.get_report(key)
    except KeyError:
        raise HTTPException(404, f"报表不存在：{key}")
    params = {"months": months, "region": region, "level": level,
              "category": category, "limit": limit}
    columns, rows = _guard(reports.run_report, key, params)
    stale, info = _stale_info()
    return {"key": key, "title": rep["title"], "columns": columns, "rows": rows,
            "stale": stale, "stale_info": info}


@app.get("/api/reports/{key}/export")
def api_report_export(key: str, months: int | None = None, region: str | None = None,
                      level: str | None = None, category: str | None = None, limit: int | None = None):
    try:
        rep = reports.get_report(key)
    except KeyError:
        raise HTTPException(404, f"报表不存在：{key}")
    params = {"months": months, "region": region, "level": level,
              "category": category, "limit": limit}
    columns, rows = _guard(reports.run_report, key, params)
    stale, info = _stale_info()
    content = export.to_xlsx(columns, rows, sheet=rep["title"], note=info)
    filename = f"{rep['title']}_{datetime.now():%Y%m%d}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


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
def api_runs():
    return {"runs": [
        {k: r.get(k) for k in ("run_id", "trigger", "started_at", "finished_at", "status", "counts")}
        for r in dbt_runner.history()
    ]}


@app.get("/api/runs/status")
def api_run_status():
    return dbt_runner.status()


@app.post("/api/runs/trigger")
def api_run_trigger(background_tasks: BackgroundTasks):
    run_id = dbt_runner.trigger_run("manual")
    if run_id is None:
        raise HTTPException(409, "已有跑批在进行中")
    return {"run_id": run_id, "message": "跑批已启动"}


@app.get("/api/runs/{run_id}")
def api_run_detail(run_id: str):
    run = next((r for r in dbt_runner.history() if r["run_id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "运行记录不存在")
    idx = artifacts.node_index()

    def _row(uid: str, n: dict):
        meta = idx["nodes"].get(uid, {})
        return {"uid": uid, "name": meta.get("name", uid.split(".")[-1] if uid else uid),
                "kind": meta.get("resource_type", uid.split(".")[0] if uid else "?"),
                "status": n.get("status"), "time": n.get("time"), "message": n.get("message")}

    nodes = [_row(uid, n) for uid, n in run.get("nodes", {}).items()]
    nodes.sort(key=lambda r: (0 if r["kind"] == "model" else 1, r["name"]))
    return {**{k: run.get(k) for k in ("run_id", "trigger", "started_at", "finished_at", "status",
                                       "ingest_ok", "ingest", "counts", "error", "dbt_returncode")},
            "nodes": nodes}


@app.get("/api/runs/{run_id}/log")
def api_run_log(run_id: str, tail: int = 300):
    run = next((r for r in dbt_runner.history() if r["run_id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "运行记录不存在")
    log_file = Path(run.get("log_file", ""))
    if not log_file.exists():
        return PlainTextResponse("(无日志)")
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return PlainTextResponse("\n".join(lines[-max(10, min(tail, 2000)):]))

# ---------------------------------------------------------------- 前端静态页
app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
