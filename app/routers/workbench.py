# -*- coding: utf-8 -*-
"""配置工作台路由：六块配置的读/校验/保存与挂起队列（v0.5，原 app/main.py，行为不变）。"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from app.services import dbt_runner
from app.services import config_workbench as workbench
from app.services.config_workbench import WorkbenchError

router = APIRouter()


@router.get("/api/config/{instance}")
def api_config_overview(instance: str):
    try:
        return workbench.overview(instance)
    except WorkbenchError as e:
        raise HTTPException(404, str(e))


@router.get("/api/config/{instance}/pending")
def api_config_pending(instance: str):
    try:
        return workbench.pending_items(instance)
    except WorkbenchError as e:
        raise HTTPException(404, str(e))


@router.get("/api/config/{instance}/impact")
def api_config_impact(instance: str):
    try:
        return workbench.impact_map(instance)
    except WorkbenchError as e:
        raise HTTPException(404, str(e))


@router.get("/api/config/{instance}/{block}")
def api_config_read(instance: str, block: str):
    try:
        return workbench.read_block(instance, block)
    except WorkbenchError as e:
        raise HTTPException(404, str(e))


def _draft_payload(payload: dict) -> str:
    content = (payload or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(422, "请求体需含非空字符串字段 content")
    return content


@router.post("/api/config/{instance}/{block}/validate")
def api_config_validate(instance: str, block: str, payload: dict = Body(...)):
    content = _draft_payload(payload)
    try:
        return workbench.validate_draft(instance, block, content)
    except WorkbenchError as e:
        raise HTTPException(404, str(e))


@router.post("/api/config/{instance}/{block}/save")
def api_config_save(instance: str, block: str, payload: dict = Body(...)):
    content = _draft_payload(payload)
    rebuild = bool((payload or {}).get("rebuild", False))
    try:
        result = workbench.save_block(instance, block, content, rebuild, dbt_runner.trigger_run)
    except WorkbenchError as e:
        raise HTTPException(404, str(e))
    if not result["ok"]:
        return JSONResponse(status_code=result["http"],
                            content={"ok": False, "errors": result["errors"]})
    return result
