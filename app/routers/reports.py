# -*- coding: utf-8 -*-
"""报表路由：清单、取数、Excel 导出、口径展示（原 app/main.py，行为不变）。"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from semantic import query as semantic_query
from semantic.loader import ConfigError, load_instance

from app.services.export import to_xlsx
from app.routers.deps import guard, current_instance, stale_info

router = APIRouter()


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


@router.get("/api/reports")
def api_reports():
    name = current_instance()
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


@router.get("/api/reports/{key}/data")
def api_report_data(key: str, request: Request, limit: int | None = None):
    try:
        rep = next(r for r in semantic_query.list_reports(current_instance()) if r["key"] == key)
    except StopIteration:
        raise HTTPException(404, f"报表不存在：{key}")
    allowed = set(semantic_query.filter_options(current_instance(), key).keys())
    filters = {k: v for k, v in request.query_params.items() if k in allowed}
    rows = guard(semantic_query.run_report, current_instance(), key, filters, limit or 500)
    cols = [(rep["dimension"], rep["dimension"])] + (
        [(rep["time_dim"], rep["time_dim"])] if rep.get("time_dim") else [])
    seen = {c for _, c in cols}
    if rows:
        for k in rows[0]:
            if k not in seen:
                cols.append((k, k))
    stale, info = stale_info()
    return {"key": key, "title": rep["title"], "columns": cols, "rows": rows,
            "stale": stale, "stale_info": info}


@router.get("/api/reports/{key}/export")
def api_report_export(key: str, request: Request, limit: int | None = None):
    try:
        rep = next(r for r in semantic_query.list_reports(current_instance()) if r["key"] == key)
    except StopIteration:
        raise HTTPException(404, f"报表不存在：{key}")
    allowed = set(semantic_query.filter_options(current_instance(), key).keys())
    filters = {k: v for k, v in request.query_params.items() if k in allowed}
    rows = guard(semantic_query.run_report, current_instance(), key, filters, limit or 5000)
    cols = [(rep["dimension"], rep["dimension"])] + (
        [(rep["time_dim"], rep["time_dim"])] if rep.get("time_dim") else [])
    if rows:
        for k in rows[0]:
            if all(k != c for c, _ in cols):
                cols.append((k, k))
    stale, info = stale_info()
    content = to_xlsx(cols, rows, sheet=rep["title"], note=info)
    filename = f"{rep['title']}_{datetime.now():%Y%m%d}.xlsx"
    return Response(content=content,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.get("/api/caliber")
def api_caliber():
    """当前账套的指标/派生列/维度口径——报表页「📐 口径」弹窗的数据源。
    口径唯一出处：instances/<账套>/metrics.yml 与 wide.yml（本端点只读展示）"""
    try:
        inst = load_instance(current_instance())
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
