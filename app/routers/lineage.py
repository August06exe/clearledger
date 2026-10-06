# -*- coding: utf-8 -*-
"""血缘与数据字典路由：图、字段级血缘、节点详情、字典（原 app/main.py，行为不变）。"""
from __future__ import annotations

import json
from datetime import datetime

import duckdb
from fastapi import APIRouter, HTTPException

from semantic.loader import ConfigError, load_instance

from app.services import dbt_runner
from app.routers.deps import current_instance

router = APIRouter()

_STATUS_TO_LIGHT = {
    "success": "green", "pass": "green", "warn": "yellow",
    "error": "red", "fail": "red", "runtime error": "red",
    "skipped": "unknown", "not_run": "unknown",
}


@router.get("/api/lineage/graph")
def api_lineage_graph():
    name = current_instance()
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


@router.get("/api/lineage/columns/{name}")
def api_lineage_columns(name: str):
    name_ = current_instance()
    manifest_path = load_instance(name_).pipeline_dir / "target" / "manifest.json"
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
        # 兜底：manifest 无列信息（生成管道的 source 不带 columns）时从库内实查，
        # 否则 SQLGlot 无 schema 可依，字段级血缘全列解析失败（v0.3 迁移遗留）
        try:
            _con0 = duckdb.connect(str((load_instance(name_).pipeline_dir / load_instance(name_).db_path).resolve()), read_only=True)
            _rows0 = _con0.execute(
                "select table_schema, table_name, column_name from information_schema.columns "
                "where table_schema in ('raw','staging','intermediate','marts')").fetchall()
            _con0.close()
            for _s, _t, _c in _rows0:
                if _t in upstream:
                    schema_map.setdefault(_t, {})[_c] = "UNKNOWN"
        except Exception:
            pass
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


@router.get("/api/node/{uid}")
def api_node_detail(uid: str):
    name_ = current_instance()
    manifest_path = load_instance(name_).pipeline_dir / "target" / "manifest.json"
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


@router.get("/api/dictionary")
def api_dictionary():
    name_ = current_instance()
    try:
        inst = load_instance(name_)
    except ConfigError as e:
        raise HTTPException(503, str(e))
    manifest_path = inst.pipeline_dir / "target" / "manifest.json"
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
