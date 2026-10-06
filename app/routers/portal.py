# -*- coding: utf-8 -*-
"""门户杂务路由：账套切换、总览、设置、别名（原 app/main.py，行为不变）。"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from semantic.loader import ConfigError, list_instances, load_instance
from semantic import query as semantic_query

from app import config
from app.services import dbt_runner, settings as settings_svc
from app.services.schedule import schedule_info, apply_schedule
from app.routers.deps import guard, current_instance

router = APIRouter()


@router.get("/api/instance")
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


@router.post("/api/instance")
def api_instance_switch(payload: dict = Body(...)):
    name = payload.get("instance")
    if not name or name not in list_instances():
        raise HTTPException(404, f"账套不存在：{name}（可用: {list_instances()}）")
    settings_svc.save({"instance": name})
    return {"current": name, "message": f"已切换到账套 {name}"}


@router.get("/api/overview")
def api_overview():
    name = current_instance()
    run = dbt_runner.latest_run(name)

    # KPI：当前账套的月度报表（monthly_kpi）最新完整月 + 前月
    kpi_rows = guard(semantic_query.run_report, name, "monthly_kpi", None, 200) \
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
        "schedule": schedule_info(),
        "kpi": {"latest": latest, "prev": prev},
        "trend": kpi_rows,
        "warnings": warns,
    }


@router.get("/api/aliases")
def api_aliases():
    from app.services.aliases import build_alias_map
    try:
        return build_alias_map(load_instance(current_instance()))
    except ConfigError as e:
        raise HTTPException(503, str(e))


@router.get("/api/settings")
def api_settings_get():
    return schedule_info()


@router.post("/api/settings")
def api_settings_patch(payload: dict = Body(...)):
    patch = {}
    if "schedule_enabled" in payload:
        patch["schedule_enabled"] = bool(payload["schedule_enabled"])
    if "ai_banner" in payload:
        patch["ai_banner"] = bool(payload["ai_banner"])
    try:
        if "hour" in payload:
            patch["schedule_hour"] = int(payload["hour"])
        if "minute" in payload:
            patch["schedule_minute"] = int(payload["minute"])
    except (TypeError, ValueError):
        raise HTTPException(422, "时间格式不对")
    settings_svc.save(patch)
    apply_schedule()
    return schedule_info()
