# -*- coding: utf-8 -*-
"""查询编译器：报表（维度×指标×筛选）→ SQL。门户报表层的数据驱动内核。

设计：只读连接实例库；筛选值白名单（distinct 实查）；参数绑定防注入。
"""
from __future__ import annotations

import time

import duckdb

from semantic.loader import ConfigError, Instance, load_instance


def _connect(inst: Instance, readonly: bool = True) -> duckdb.DuckDBPyConnection:
    db = (inst.pipeline_dir / inst.db_path).resolve()
    last = None
    for _ in range(20):
        try:
            return duckdb.connect(str(db), read_only=readonly)
        except duckdb.IOException as e:
            last = e
            time.sleep(0.5)
    raise RuntimeError(f"实例库被占用: {db}（{last}）")


def list_reports(instance: str) -> list[dict]:
    """门户报表注册表（从 dashboard.yml 生成）"""
    inst = load_instance(instance)
    out = []
    for rep in inst.dashboard.get("reports", []):
        out.append({
            "key": rep["key"], "title": rep["title"],
            "dimension": rep["dimension"], "time_dim": rep.get("time_dim"),
            "metrics": rep.get("metrics", []), "chart": rep.get("chart", "bar_line"),
        })
    return out


def filter_options(instance: str, report_key: str) -> dict[str, list]:
    """报表可筛选项（白名单的机器来源：实查 distinct）"""
    inst = load_instance(instance)
    rep = _get_report(inst, report_key)
    con = _connect(inst)
    try:
        dim = inst.dimension(rep["dimension"])
        if dim.get("type") == "time":
            return {}
        col = f'"{dim["name"]}"'
        rows = con.execute(
            f'select distinct {col} from marts.mart_{report_key} where {col} is not null order by 1'
        ).fetchall()
        return {rep["dimension"]: [r[0] for r in rows]}
    finally:
        con.close()


def build_query(instance: str, report_key: str, filters: dict | None = None,
                limit: int = 500) -> tuple[str, list]:
    """编译报表查询 → (sql, params)。filters={维度名: 值}，值必须在白名单内，否则忽略。"""
    inst = load_instance(instance)
    rep = _get_report(inst, report_key)
    opts = filter_options(instance, report_key)
    sql = f'select * from marts.mart_{report_key}'
    conds, params = [], []
    for dim_name, val in (filters or {}).items():
        if dim_name not in opts or val not in opts[dim_name]:
            continue  # 非白名单 → 静默忽略（决策 D14 同源）
        conds.append(f'"{dim_name}" = ?')
        params.append(val)
    if conds:
        sql += " where " + " and ".join(conds)
    if rep.get("time_dim") or inst.dimension(rep["dimension"]).get("type") == "time":
        tcol = f'"{rep.get("time_dim") or rep["dimension"]}"'
        sql += f" order by {tcol}"
    sql += f" limit {max(1, min(int(limit), 5000))}"
    return sql, params


def run_report(instance: str, report_key: str, filters: dict | None = None,
               limit: int = 500) -> list[dict]:
    sql, params = build_query(instance, report_key, filters, limit)
    inst = load_instance(instance)
    con = _connect(inst)
    try:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        # Decimal/date → JSON 安全
        import datetime as _dt
        from decimal import Decimal
        for r in rows:
            for k, v in r.items():
                if isinstance(v, Decimal):
                    r[k] = float(v)
                elif isinstance(v, _dt.datetime):
                    r[k] = v.strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(v, _dt.date):
                    r[k] = v.isoformat()
        return rows
    finally:
        con.close()


def _get_report(inst: Instance, key: str) -> dict:
    for rep in inst.dashboard.get("reports", []):
        if rep["key"] == key:
            return rep
    raise ConfigError(f"实例 [{inst.name}] 无报表 {key}")


if __name__ == "__main__":
    import json
    import sys
    inst_name = sys.argv[1] if len(sys.argv) > 1 else "sales"
    key = sys.argv[2] if len(sys.argv) > 2 else None
    reps = list_reports(inst_name)
    if not key:
        print(json.dumps(reps, ensure_ascii=False, indent=1))
    else:
        rows = run_report(inst_name, key, limit=5)
        print(json.dumps(rows, ensure_ascii=False, indent=1, default=str))
