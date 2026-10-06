# -*- coding: utf-8 -*-
"""开放接口路由（agent 用，钥匙鉴权 + 审计留痕，原 app/main.py，行为不变）。"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from semantic import query as semantic_query
from semantic.loader import list_instances, load_instance

from app import config
from app.services import dbt_runner, settings as settings_svc
from app.routers.deps import guard

router = APIRouter()


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


@router.get("/api/open/reports")
def api_open_reports(request: Request, instance: str | None = None):
    principal, inst_name = _open_instance(request, instance)
    return {"principal": principal, "reports": semantic_query.list_reports(inst_name)}


@router.get("/api/open/metrics")
def api_open_metrics(request: Request, instance: str | None = None):
    principal, inst_name = _open_instance(request, instance)
    inst = load_instance(inst_name)
    return {"principal": principal, "metrics": [
        {"name": m["name"], "expr": m.get("expr"), "desc": m.get("desc")} for m in inst.metrics]}


@router.get("/api/open/reports/{key}/data")
def api_open_report_data(key: str, request: Request, limit: int | None = None, instance: str | None = None):
    principal, inst_name = _open_instance(request, instance)
    try:
        rep = next(r for r in semantic_query.list_reports(inst_name) if r["key"] == key)
    except StopIteration:
        raise HTTPException(404, f"报表不存在：{key}")
    allowed = set(semantic_query.filter_options(inst_name, key).keys())
    filters = {k: v for k, v in request.query_params.items() if k in allowed}
    rows = guard(semantic_query.run_report, inst_name, key, filters, limit or 200)
    _audit_open(request, principal, True, f"report={key} rows={len(rows)}")
    # columns 与 MCP query_report 对齐（外部 agent 消费面一致性）
    return {"instance": inst_name, "key": key,
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows, "count": len(rows)}


@router.get("/api/open/status")
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
