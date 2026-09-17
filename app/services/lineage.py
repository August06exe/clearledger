# -*- coding: utf-8 -*-
"""血缘服务

- 表级血缘：直接来自 dbt manifest 的依赖图（蜘蛛网图的数据源）
- 字段级血缘：用 SQLGlot 解析模型的编译后 SQL，得到"输出字段 ← 上游表.字段"。
  这是尽力而为（best-effort）：解析失败的列会标记 unavailable，前端优雅降级。
  覆盖范围：直接上游（跨层追踪由前端沿图逐层下钻完成）。
"""
from __future__ import annotations

import re

from app.services import artifacts


def graph() -> dict:
    idx = artifacts.node_index()
    nodes, edges = [], []
    for uid, n in idx["nodes"].items():
        nodes.append({
            "uid": uid,
            "name": n["name"],
            "resource_type": n["resource_type"],
            "schema": n["schema"],
            "description": n["description"],
            "column_count": len(n["columns"]),
            "test_count": len(n["tests"]),
            "tags": n["tags"],
        })
        for dep in n["depends_on"]:
            if dep in idx["nodes"]:
                edges.append({"source": dep, "target": uid})
    m = artifacts.manifest() or {}
    return {
        "nodes": nodes,
        "edges": edges,
        "generated_at": (m.get("metadata") or {}).get("generated_at"),
    }


def _simplify_refs(sql: str, names: list[str]) -> str:
    """把编译后 SQL 里的 "db"."schema"."model" 引用统一改写为裸模型名，便于 SQLGlot 映射"""
    for nm in sorted(set(names), key=len, reverse=True):
        pattern = rf'(?:"?[\w]+"?\.)+"?{re.escape(nm)}"?(?![\w])'
        sql = re.sub(pattern, nm, sql)
    return sql


def column_lineage(name: str) -> dict:
    idx = artifacts.node_index()
    node = next(
        (n for n in idx["nodes"].values()
         if n["name"] == name and n["resource_type"] == "model"),
        None,
    )
    if node is None:
        return {"model": name, "available": False, "reason": "模型不存在", "columns": []}
    sql = node.get("compiled_code")
    if not sql:
        return {"model": name, "available": False, "reason": "暂无编译后 SQL（先跑一次批）", "columns": []}

    upstreams = [idx["nodes"][uid] for uid in node["depends_on"] if uid in idx["nodes"]]
    up_names = [u["name"] for u in upstreams]
    schema_map = {u["name"]: {c: "UNKNOWN" for c in u["columns"]} for u in upstreams}
    sql_simple = _simplify_refs(sql, up_names)

    try:
        import sqlglot
        from sqlglot.lineage import lineage as sg_lineage
    except Exception as e:  # pragma: no cover
        return {"model": name, "available": False, "reason": f"SQLGlot 不可用：{e}", "columns": []}

    result = []
    for col, meta in node["columns"].items():
        entry = {"column": col, "description": meta.get("description"), "upstreams": [], "ok": True}
        try:
            root = sg_lineage(col, sql_simple, schema=schema_map, dialect="duckdb")
            seen: set[tuple[str, str]] = set()
            for n in root.walk():
                src = getattr(n, "source", None)
                if isinstance(src, sqlglot.exp.Table):
                    tbl = src.name
                    raw = str(getattr(n, "name", ""))
                    col_part = raw.split(":", 1)[0].strip()
                    if "." in col_part:  # 去掉 SQL 别名前缀（如 e.order_date → order_date）
                        col_part = col_part.rsplit(".", 1)[-1]
                    if ":" in raw or col_part in ("", "*"):
                        col_part = "*"
                    if tbl == name and col_part == col:
                        continue  # 跳过输出列自身
                    key = (tbl, col_part)
                    if key not in seen:
                        seen.add(key)
                        entry["upstreams"].append({"table": tbl, "column": col_part})
        except Exception:
            entry["ok"] = False
        result.append(entry)

    return {"model": name, "available": True, "columns": result}
