# -*- coding: utf-8 -*-
"""界面中文化（v0.4）：技术名 → 中文别名的统一解析

别名全部从六份配置推导，不新增维护负担：
- 源表/清洗表名  ← sources.yml 的 title（raw 与 stg_ 同名同译，靠图层区分）
- 宽表模型名     ← "{主源标题}宽表"
- 报表模型名     ← dashboard.yml 的 report title
- 字段名         ← sources.yml 字段 cn / dimensions.yml 维度中文名
查不到的技术名原样返回——别名层只做展示增强，不改变任何数据层命名（红线）。
"""
from __future__ import annotations


def build_alias_map(inst) -> dict:
    """返回 {"nodes": {技术名: 中文}, "fields": {技术名: 中文}}。"""
    nodes: dict[str, str] = {}
    fields: dict[str, str] = {}

    main_title = ""
    for src in inst.sources.get("sources", []):
        title = (src.get("title") or "").strip()
        if not title:
            continue
        nodes[src["name"]] = title
        nodes[f"stg_{src['name']}"] = title
        if src["name"] == inst.wide.get("wide", {}).get("main"):
            main_title = title
        for f in src.get("fields", []):
            cn = (f.get("cn") or "").strip()
            if cn and f.get("map"):
                fields[f["map"]] = cn

    wide = inst.wide.get("wide", {})
    if wide.get("name"):
        nodes[f"int_{wide['name']}"] = f"{main_title}宽表" if main_title else "宽表"
    for d in wide.get("derived", []):
        pass  # 派生列以 desc 作为口径说明展示，不再造别名

    for dim in inst.dimensions:
        cn = (dim.get("name") or "").strip()
        if cn and dim.get("column"):
            fields[dim["column"]] = cn

    for rep in inst.dashboard.get("reports", []):
        title = (rep.get("title") or "").strip()
        if title and rep.get("key"):
            nodes[f"mart_{rep['key']}"] = title

    return {"nodes": nodes, "fields": fields}


def alias(name: str | None, amap: dict) -> str | None:
    """单名解析；查不到返回原名。"""
    if not name:
        return name
    return amap.get("nodes", {}).get(name) or name
