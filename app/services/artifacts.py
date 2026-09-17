# -*- coding: utf-8 -*-
"""dbt 产物解析：manifest.json（结构/血缘/字典）与 run_results.json（运行结果）"""
from __future__ import annotations

import json
from pathlib import Path

from app import config

_FAIL_STATES = {"error", "fail", "runtime error"}

_cache: dict[str, tuple[float, object]] = {}


def _load_cached(path: Path, key: str):
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cached = _cache.get(key)
    if cached is None or cached[0] != mtime:
        _cache[key] = (mtime, json.loads(path.read_text(encoding="utf-8")))
    return _cache[key][1]


def manifest() -> dict | None:
    return _load_cached(config.MANIFEST, "manifest")


def run_results() -> dict | None:
    return _load_cached(config.RUN_RESULTS, "run_results")


def node_index() -> dict:
    """把 manifest 整理成前端友好的节点索引：

    nodes[uid] = {uid, name, resource_type, schema, description, columns{...},
                  tags, path, depends_on[], tests[], compiled_code}
    tests: 附着在模型/源上的测试元信息
    """
    m = manifest()
    if not m:
        return {"nodes": {}, "tests": {}}
    nodes: dict[str, dict] = {}
    tests: dict[str, dict] = {}

    all_nodes = {**m.get("nodes", {}), **m.get("sources", {})}
    for uid, n in all_nodes.items():
        rt = n.get("resource_type")
        if rt in ("model", "seed", "snapshot", "source"):
            nodes[uid] = {
                "uid": uid,
                "name": n.get("name"),
                "resource_type": rt,
                "schema": n.get("schema"),
                "database": n.get("database"),
                "description": (n.get("description") or "").strip(),
                "columns": {
                    c: {"name": c, "description": (meta.get("description") or "").strip()}
                    for c, meta in (n.get("columns") or {}).items()
                },
                "tags": n.get("tags") or [],
                "path": n.get("original_file_path"),
                "depends_on": (n.get("depends_on") or {}).get("nodes", []),
                "compiled_code": n.get("compiled_code"),
                "tests": [],
            }
        elif rt == "test":
            tested = ((n.get("depends_on") or {}).get("nodes") or [None])[0]
            tests[uid] = {
                "uid": uid,
                "name": n.get("name"),
                "kind": (n.get("test_metadata") or {}).get("name") or "自定义",
                "tested_node": tested,
                "severity": ((n.get("config") or {}).get("severity")) or "error",
            }

    for t in tests.values():
        parent = nodes.get(t["tested_node"])
        if parent is not None:
            parent["tests"].append(
                {"uid": t["uid"], "name": t["name"], "kind": t["kind"], "severity": t["severity"]}
            )
    return {"nodes": nodes, "tests": tests}


def derive_status(node_status: dict[str, str]) -> str:
    """由各节点状态推导整体红绿灯：red > yellow > green"""
    states = set(node_status.values())
    if states & _FAIL_STATES:
        return "red"
    if "warn" in states:
        return "yellow"
    return "green"
