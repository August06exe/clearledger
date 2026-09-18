# -*- coding: utf-8 -*-
"""编译器：五配置 → 完整 dbt project（写入 instances/<n>/pipeline/，生成物进 git 可审计）

用法：.venv/Scripts/python -m semantic.compile_dbt --instance sales
生成：staging（字段契约→清洗模型+测试）/ intermediate（宽表+匹配契约测试）
     / marts（报表=维度×指标汇总）。重新编译前报告与旧产物的 diff 摘要。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from semantic.loader import ConfigError, load_instance

TYPE_CAST = {
    "string": 'trim(cast({col} as varchar))',
    "date": 'cast({col} as date)',
    "integer": 'cast({col} as bigint)',
    "decimal": 'cast({col} as decimal(18, 4))',
    "bool": 'cast({col} as boolean)',
}


def _sql_str(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def gen_staging_model(src: dict) -> str:
    name = src["name"]
    fields = src.get("fields", [])
    exprs, wheres = [], []
    for f in fields:
        col = f["map"]
        cast = TYPE_CAST.get(f.get("type", "string"), TYPE_CAST["string"]).format(col=col)
        if f.get("missing") == "default" and "default" in f:
            cast = f"coalesce({cast}, {_sql_str(f['default'])})"
        exprs.append(f"    {cast} as {col}")
        if f.get("required"):
            wheres.append(f"{col} is not null")
    body = ",\n".join(exprs)
    where = ("\nwhere " + "\n  and ".join(wheres)) if wheres else ""
    return (f"-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）\n"
            f"select\n{body}\nfrom {{{{ source('raw', '{name}') }}}}{where}\n")


def gen_staging_yml(src: dict) -> str:
    name = src["name"]
    lines = [f"version: 2\n\nmodels:", f"  - name: stg_{name}",
             f"    description: {src.get('title', name)}（清洗层，由字段契约生成）", "    columns:"]
    for f in src.get("fields", []):
        col = f["map"]
        lines.append(f"      - name: {col}")
        lines.append(f"        description: {f['cn']}（{f.get('type', 'string')}）")
        tests = []
        if f.get("required"):
            tests.append("not_null")
        if f.get("unique"):
            tests.append("unique")
        if f.get("enum"):
            vals = ", ".join(_sql_str(v) for v in f["enum"])
            tests.append(f"accepted_values:\n              arguments:\n                values: [{vals}]")
        if tests:
            lines.append("        data_tests:")
            for t in tests:
                lines.append(f"          - {t}")
    return "\n".join(lines) + "\n"


def gen_sources_yml(inst) -> str:
    lines = ["version: 2\n\nsources:", "  - name: raw", "    schema: raw",
             "    description: 原始层（实例摄取写入，含契约校验后的规整数据）", "    tables:"]
    for src in inst.sources.get("sources", []):
        lines.append(f"      - name: {src['name']}")
        lines.append(f"        description: {src.get('title', src['name'])}")
    return "\n".join(lines) + "\n"


def gen_wide_model(inst) -> str:
    wide = inst.wide["wide"]
    main = wide["main"]
    joins = wide.get("joins", [])
    drop = set(wide.get("drop", []))

    main_cols = [f["map"] for f in inst.fields_of(main)
                 if f["map"] not in drop]
    select_parts = [f"    m.{c}" for c in main_cols]
    from_sql = f"{{{{ ref('stg_{main}') }}}} m"
    for i, j in enumerate(joins):
        alias = f"d{i}"
        for c in j.get("columns", []):
            select_parts.append(f"    {alias}.{c}")
    join_sql = ""
    for i, j in enumerate(joins):
        alias = f"d{i}"
        how = j.get("how", "left")
        keys = j["keys"]
        join_sql += (f"\n{how} join {{{{ ref('stg_{j['table']}') }}}} {alias}"
                     f"\n  on m.{keys['left']} = {alias}.{keys['right']}")
    derived = ""
    for d in wide.get("derived", []):
        select_parts.append(f"    {d['expr']} as {d['name']}")

    return (f"-- 生成物：宽表装配（{main} + {len(joins)} 张标签表左联 + 派生列）\n"
            f"select\n" + ",\n".join(select_parts) + f"\nfrom {from_sql}{join_sql}\n")


def gen_match_tests(inst) -> list[tuple[str, str]]:
    """匹配契约 → dbt 数据测试。fanout=维表键重复（扇出风险）；null_match=主表键匹空"""
    wide = inst.wide["wide"]
    main = wide["main"]
    out: list[tuple[str, str]] = []
    for j in wide.get("joins", []):
        c = j.get("contract", {})
        tbl, on = j["table"], j["keys"]
        sev_fanout = "error" if c.get("fanout", "red") == "red" else "warn"
        out.append((
            f"match_{tbl}_fanout.sql",
            f"{{{{ config(severity='{sev_fanout}') }}}}\n"
            f"-- 匹配契约：{tbl} 的键 {on['right']} 必须唯一，否则 join 扇出/笛卡尔积\n"
            f"select {on['right']}\nfrom {{{{ ref('stg_{tbl}') }}}}\n"
            f"group by 1 having count(*) > 1\n"))
        if c.get("null_match", "yellow") != "ignore":
            sev_null = "error" if c.get("null_match") == "red" else "warn"
            out.append((
                f"match_{tbl}_null_match.sql",
                f"{{{{ config(severity='{sev_null}') }}}}\n"
                f"-- 匹配契约：主表 {on['left']} 在 {tbl} 中匹空的清单（未匹配标签）\n"
                f"select distinct m.{on['left']}\nfrom {{{{ ref('stg_{main}') }}}} m\n"
                f"left join {{{{ ref('stg_{tbl}') }}}} d on m.{on['left']} = d.{on['right']}\n"
                f"where m.{on['left']} is not null and d.{on['right']} is null\n"))
    return out


def _dim_expr(dim: dict, col: str) -> str:
    if dim.get("type") == "time":
        grain = dim.get("grain", "month")
        return f"date_trunc('{grain}', {col}) as \"{dim['name']}\""
    return f"{col} as \"{dim['name']}\""


def gen_mart_model(inst, rep: dict) -> str:
    wide = inst.wide["wide"]["name"]
    dim = inst.dimension(rep["dimension"])
    has_time = bool(rep.get("time_dim"))
    time_dim = inst.dimension(rep["time_dim"]) if has_time else dim if dim.get("type") == "time" else None

    group_cols = []
    if time_dim is not None and has_time:
        group_cols.append(_dim_expr(time_dim, time_dim["column"]))
    group_cols.append(_dim_expr(dim, dim["column"]))
    metrics = [f"    {inst.metric(m)['expr']} as \"{m}\"" for m in rep.get("metrics", [])]

    where = ""
    if rep.get("full_period_only") and time_dim is not None:
        grain = time_dim.get("grain", "month")
        where = f"\nwhere date_trunc('{grain}', {time_dim['column']}) < date_trunc('{grain}', current_date)"

    group_by = ", ".join(str(i + 1) for i in range(len(group_cols)))
    return (f"-- 生成物：报表汇总模型（{rep['title']} = 维度×指标）\n"
            f"select\n" + ",\n".join(group_cols + metrics) +
            f"\nfrom {{{{ ref('int_{wide}') }}}}{where}\ngroup by {group_by}\n")


def gen_project_files(inst) -> dict[str, str]:
    n = inst.name
    project_yml = f"""# 生成物：由 semantic.compile_dbt 从 instances/{n}/ 五配置生成，勿手改
name: cl_{n}
version: "1.0.0"
config-version: 2
profile: cl

model-paths: ["models"]
macro-paths: ["macros"]
test-paths: ["tests"]
clean-targets: ["target"]

models:
  cl_{n}:
    +materialized: view
    staging:
      +schema: staging
    intermediate:
      +schema: intermediate
    marts:
      +schema: marts
      +materialized: table
"""
    profiles_yml = f"""# 生成物：实例 {n} 的 dbt 连接（库文件独立，实例间物理隔离）
cl:
  target: {n}
  outputs:
    {n}:
      type: duckdb
      path: "{inst.db_path.as_posix()}"
      threads: 4
"""
    macro = """{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
"""
    return {"dbt_project.yml": project_yml, "profiles.yml": profiles_yml,
            "macros/generate_schema_name.sql": macro}


def compile_instance(inst) -> dict:
    files: dict[str, str] = {}
    files.update(gen_project_files(inst))

    # staging
    st = inst.pipeline_dir / "models" / "staging"
    files["models/staging/sources.yml"] = gen_sources_yml(inst)
    for src in inst.sources.get("sources", []):
        files[f"models/staging/stg_{src['name']}.sql"] = gen_staging_model(src)
        files[f"models/staging/stg_{src['name']}.yml"] = gen_staging_yml(src)

    # intermediate（宽表）
    files[f"models/intermediate/int_{inst.wide['wide']['name']}.sql"] = gen_wide_model(inst)

    # 匹配契约测试
    for fname, content in gen_match_tests(inst):
        files[f"tests/{fname}"] = content

    # marts
    for rep in inst.dashboard.get("reports", []):
        files[f"models/marts/mart_{rep['key']}.sql"] = gen_mart_model(inst, rep)

    # diff 摘要（AI-Native：生成物变更可审计）
    changed, unchanged = [], 0
    for rel, content in files.items():
        p = inst.pipeline_dir / rel
        old = p.read_text(encoding="utf-8") if p.exists() else None
        if old == content:
            unchanged += 1
        else:
            changed.append(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    return {"total": len(files), "changed": changed, "unchanged": unchanged}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True)
    args = ap.parse_args()
    try:
        inst = load_instance(args.instance)
        r = compile_instance(inst)
    except ConfigError as e:
        print(f"[config] {e}", file=sys.stderr)
        return 2

    print(f"编译完成：{r['total']} 个文件（变更 {len(r['changed'])} / 未变 {r['unchanged']}）")
    for c in r["changed"]:
        print(f"  ~ {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
