# -*- coding: utf-8 -*-
"""编译器：五配置 → 完整 dbt project（写入 instances/<n>/pipeline/，生成物进 git 可审计）

用法：.venv/Scripts/python -m semantic.compile_dbt --instance sales
生成：staging（字段契约→清洗模型+测试）/ intermediate（宽表+匹配契约测试）
     / marts（报表=维度×指标汇总）。重新编译前报告与旧产物的 diff 摘要。
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
    lines = ["version: 2\n\nmodels:", f"  - name: stg_{name}",
             f"    description: {src.get('title', name)}（清洗层，由字段契约生成）", "    columns:"]

    def sev_of(level: str) -> str:
        # 字段契约 level → dbt severity（ingest 层与 dbt 层灯色一致，评审拍板 P-04）
        return "error" if level == "red" else "warn"

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
            if f.get("level", "yellow") != "red":
                tests.append(f"accepted_values:\n              arguments:\n                values: [{vals}]"
                             f"\n              config:\n                severity: warn")
            else:
                tests.append(f"accepted_values:\n              arguments:\n                values: [{vals}]")
        if tests:
            lines.append("        data_tests:")
            for t in tests:
                lines.append(f"          - {t}")
    return "\n".join(lines) + "\n"


def gen_range_tests(src: dict) -> list[tuple[str, str]]:
    """P-03：range 契约编译为 dbt 测试（severity 按字段 level）"""
    out = []
    for f in src.get("fields", []):
        if not f.get("range") or f.get("type") not in ("integer", "decimal"):
            continue
        col, rng, level = f["map"], f["range"], f.get("level", "yellow")
        out.append((
            f"range_{src['name']}_{col}.sql",
            f"{{{{ config(severity='{'error' if level == 'red' else 'warn'}') }}}}\n"
            f"-- 字段契约：{f['cn']} 范围 [{rng[0]}, {rng[1]}]\n"
            f"select {col}\nfrom {{{{ ref('stg_{src['name']}') }}}}\n"
            f"where {col} < {rng[0]} or {col} > {rng[1]}\n"))
    return out


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

    main_fields = [f["map"] for f in inst.fields_of(main) if f["map"] not in drop]
    # 有序左联（设计 §3.2）：维护 可用列→来源别名 映射，后序 join 的左键可引用前序 join 的输出列
    col_src: dict[str, str] = {c: "m" for c in main_fields}
    select_parts = [f"    m.{c}" for c in main_fields]
    from_sql = f"{{{{ ref('stg_{main}') }}}} m"
    join_sql = ""
    for i, j in enumerate(joins):
        alias = f"d{i}"
        keys = j["keys"]
        left = keys["left"]
        if left in col_src:
            left_ref = f"{col_src[left]}.{left}"
        else:  # loader 已校验，双保险
            raise KeyError(f"join 左键 {left} 不在主表或前序 join 的可用列中")
        join_sql += (f"\n{j.get('how', 'left')} join {{{{ ref('stg_{j['table']}') }}}} {alias}"
                     f"\n  on {left_ref} = {alias}.{keys['right']}")
        for c in j.get("columns", []):
            select_parts.append(f"    {alias}.{c}")
            col_src[c] = alias

    for d in wide.get("derived", []):
        select_parts.append(f'    {d["expr"]} as "{d["name"]}"')

    return (f"-- 生成物：宽表装配（{main} + {len(joins)} 张标签表有序左联 + 派生列）\n"
            f"select\n" + ",\n".join(select_parts) + f"\nfrom {from_sql}{join_sql}\n")


def gen_match_tests(inst) -> list[tuple[str, str]]:
    """匹配契约 → dbt 数据测试。fanout=维表键重复（扇出风险）；null_match=主表键匹空；
    orphan_right 非 ignore=右表孤儿清单（warn）——契约策略组合全部被尊重（N-03/N-04）"""
    wide = inst.wide["wide"]
    main = wide["main"]
    out: list[tuple[str, str]] = []
    for j in wide.get("joins", []):
        c = j.get("contract", {})
        tbl, on = j["table"], j["keys"]
        if c.get("fanout", "red") != "ignore":
            sev_fanout = "error" if c.get("fanout", "red") == "red" else "warn"
            out.append((
                f"match_{tbl}_fanout.sql",
                f"{{{{ config(severity='{sev_fanout}') }}}}\n"
                f"-- 匹配契约：{tbl} 的键 {on['right']} 必须唯一，否则 join 扇出/笛卡尔积\n"
                f"select {on['right']}\nfrom {{{{ ref('stg_{tbl}') }}}}\n"
                f"group by 1 having count(*) > 1\n"))
        if c.get("null_match", "yellow") != "ignore":
            sev_null = "error" if c.get("null_match") == "red" else "warn"
            # 从宽表 anti-join 维表：天然支持链式左键（左列可能来自前序 join 的输出列）
            out.append((
                f"match_{tbl}_null_match.sql",
                f"{{{{ config(severity='{sev_null}') }}}}\n"
                f"-- 匹配契约：主表 {on['left']} 在 {tbl} 中匹空的清单（未匹配标签）\n"
                f"select distinct w.{on['left']}\n"
                f"from {{{{ ref('int_{wide['name']}') }}}} w\n"
                f"where w.{on['left']} is not null\n"
                f"  and not exists (\n"
                f"    select 1 from {{{{ ref('stg_{tbl}') }}}} d\n"
                f"    where d.{on['right']} = w.{on['left']})\n"))
        orphan = c.get("orphan_right", "ignore")
        if orphan not in ("ignore",):
            out.append((
                f"match_{tbl}_orphan_right.sql",
                f"{{{{ config(severity='warn') }}}}\n"
                f"-- 匹配契约：{tbl} 有键但主表无流水的孤儿清单（仅记录）\n"
                f"select distinct d.{on['right']}\nfrom {{{{ ref('stg_{tbl}') }}}} d\n"
                f"left join {{{{ ref('stg_{main}') }}}} m on d.{on['right']} = m.{on['left']}\n"
                f"where m.{on['left']} is null\n"))
    return out


def _dim_expr(dim: dict, col: str) -> str:
    if dim.get("type") == "time":
        grain = dim.get("grain", "month")
        return f"date_trunc('{grain}', {col}) as \"{dim['name']}\""
    return f"{col} as \"{dim['name']}\""


_SQL_KW = {"sum", "count", "distinct", "round", "nullif", "coalesce", "null", "cast",
           "as", "date_trunc", "abs", "min", "max", "avg", "case", "when", "then",
           "else", "end", "and", "or", "not", "in", "true", "false"}


def _report_graph(inst):
    """报表 index / base→children / 各报表所需维度(含后代传导) / 各报表子树指标 token 集合"""
    import re
    reps = {r["key"]: r for r in inst.dashboard.get("reports", [])}
    children = {}
    for r in reps.values():
        if r.get("base"):
            children.setdefault(r["base"], []).append(r["key"])

    def required_dims(key):
        rep = reps[key]
        own = []
        if rep.get("time_dim"):
            own.append(rep["time_dim"])
        own.append(rep["dimension"])
        out = list(own)
        for c in children.get(key, []):
            for d in required_dims(c):
                if d not in out:
                    out.append(d)
        # 粒度契约（方向一）：后代传导维度超出本报表声明维度的部分，
        # 必须在本报表 rollup 中显式声明——杜绝静默改粒度
        declared = set(own) | set(rep.get("rollup") or [])
        extra = [d for d in out if d not in declared]
        if extra:
            raise ConfigError(
                f"[{inst.name}] 报表 {key} 的下级报表需要按 {extra} 分组，"
                f"这会改变本报表粒度——请在 rollup 中显式声明"
                f"（如 rollup: {extra}），或调整下级报表维度")
        return out

    def subtree_tokens(key):
        out = set()
        stack = [key]
        while stack:
            k = stack.pop()
            for m in reps[k].get("metrics", []):
                expr = inst.metric(m)["expr"]
                out |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr)) - _SQL_KW
            stack.extend(children.get(k, []))
        return out

    req = {k: required_dims(k) for k in reps}
    tok = {k: subtree_tokens(k) for k in reps}
    return reps, children, req, tok


def gen_mart_model(inst, rep: dict, ctx=None) -> str:
    """报表汇总模型统一生成器。

    - 无 base：从 int_wide 直出（与历史路径字节级等价——无后代时逐字符一致）；
    - 有 base：从上级 mart 卷聚合，支撑利润阶梯式级联；
    - 有后代（被分层引用）：分组维度并入后代传导维度，并携带后代指标 expr
      引用的全部可加列（sum(col) as col），使下层同口径 expr 可逐字复用。
    """
    import re
    wide = inst.wide["wide"]["name"]
    dim = inst.dimension(rep["dimension"])
    has_time = bool(rep.get("time_dim"))
    time_dim = inst.dimension(rep["time_dim"]) if has_time else dim if dim.get("type") == "time" else None

    base_key = rep.get("base")
    ctx = ctx or _report_graph(inst)
    reps, children, req, tok = ctx
    key = rep["key"]

    group_cols = []
    if base_key:
        # 上级 mart 的实际输出列 = 其维度 + 其指标别名 + 其 carry（全部子树 token 并集）
        base_carry = set()
        for c in children.get(base_key, []):
            base_carry |= tok[c]
        base_cols = (set(req[base_key]) | set(reps[base_key].get("metrics", [])) | base_carry)
        for dn in req[key]:
            if dn not in base_cols:
                raise ConfigError(f"[{inst.name}] 分层报表 {key} 的维度 [{dn}] 不在上级报表 {base_key} 的粒度中")
            group_cols.append(f'    "{dn}"')
    else:
        # 无 base：从宽表直出，但后代传导维度同样并入分组（如部门需在项目层预挂）
        for dn in req[key]:
            d = inst.dimension(dn)
            if dn == rep.get("time_dim") and has_time:
                group_cols.append(_dim_expr(time_dim, time_dim["column"]))
            else:
                group_cols.append(_dim_expr(d, d["column"]))

    metrics = [f"    {inst.metric(m)['expr']} as \"{m}\"" for m in rep.get("metrics", [])]

    carry_lines = []
    child_tokens = set()
    for c in children.get(key, []):
        child_tokens |= tok[c]
    own_out = set(req[key]) | set(rep.get("metrics", []))
    # 注意：本级输出 ≠ 上级输出——上级 carry 的列本级仍须重带（sum 可加，逐层重聚合）
    for col in sorted(child_tokens - own_out):
        if base_key and col not in base_cols:
            raise ConfigError(f"[{inst.name}] 分层报表 {key} 的后代引用列 [{col}] 不在上级报表 {base_key} 输出中")
        carry_lines.append(f'    sum("{col}") as "{col}"')

    where = ""
    if not base_key and rep.get("full_period_only") and time_dim is not None:
        grain = time_dim.get("grain", "month")
        where = f"\nwhere date_trunc('{grain}', {time_dim['column']}) < date_trunc('{grain}', current_date)"

    group_by = ", ".join(str(i + 1) for i in range(len(group_cols)))
    src = (f"{{{{ ref('mart_{base_key}') }}}}" if base_key
           else f"{{{{ ref('int_{wide}') }}}}")
    head = (f"-- 生成物：分层报表模型（{rep['title']} ← {base_key}）\n" if base_key
            else f"-- 生成物：报表汇总模型（{rep['title']} = 维度×指标）\n")
    out = (head + f"select\n" + ",\n".join(group_cols + metrics + carry_lines)
           + f"\nfrom {src}{where}")
    out += f"\ngroup by {group_by}" if group_by else ""
    return out + "\n"




def contract_test_meta(inst) -> list[dict]:
    """匹配契约测试的元数据清单（跑批收获进 raw.contract_report 用）：
    test=测试名（去 .sql）、wide=宽表声明名、field=join 左键、rule、level（red/yellow）"""
    wide = inst.wide["wide"]
    main = wide["main"]
    out = []
    for j in wide.get("joins", []):
        c = j.get("contract", {})
        tbl, on = j["table"], j["keys"]
        if c.get("fanout", "red") != "ignore":
            out.append({"test": f"match_{tbl}_fanout", "wide": wide["name"],
                        "table": tbl, "field": on["left"], "rule": "fanout",
                        "level": "red" if c.get("fanout") == "red" else "yellow"})
        if c.get("null_match", "yellow") != "ignore":
            out.append({"test": f"match_{tbl}_null_match", "wide": wide["name"],
                        "table": tbl, "field": on["left"], "rule": "null_match",
                        "level": "red" if c.get("null_match") == "red" else "yellow"})
        orphan = c.get("orphan_right", "ignore")
        if orphan not in ("ignore",):
            out.append({"test": f"match_{tbl}_orphan_right", "wide": wide["name"],
                        "table": tbl, "field": on["left"], "rule": "orphan_right",
                        "level": "yellow"})
    return out




def gen_mart_yml(inst, rep: dict) -> str:
    """mart 模型的列元数据（维度 + 指标），供数据字典/字段级血缘/分层面板消费。
    分层 mart 的 carry 列是内部实现细节，不进文档（对用户暴露的是维度×指标）。"""
    def esc(t: str) -> str:
        return str(t).replace('"', "'")
    cols = []
    if rep.get("time_dim"):
        td = inst.dimension(rep["time_dim"])
        cols.append((td["name"], f"时间维度（{td.get('grain', 'month')}）"))
    d = inst.dimension(rep["dimension"])
    cols.append((d["name"], "分组维度"))
    for m in rep.get("metrics", []):
        cols.append((m, inst.metric(m).get("desc", "")))
    lines = [f"# 生成物：报表模型列元数据（{rep['title']}）", "version: 2", "",
             "models:", f"  - name: mart_{rep['key']}",
             f"    description: {esc(rep['title'])}（维度 × 指标汇总）", "    columns:"]
    for name, desc in cols:
        lines.append(f'      - name: "{name}"')
        if desc:
            lines.append(f"        description: {esc(desc)}")
    return "\n".join(lines) + "\n"


def _is_additive(expr: str) -> bool:
    """指标可加性启发式（v0，方向一勾稽用；方向二类型系统落地后由 type 取代）：
    只允许 sum(...) 聚合与 + - 算术；出现除法（nullif 配平除外不可辨，一律视为比率）
    或非 sum 聚合（avg/max/min/count）即视为不可加，勾稽测试豁免。"""
    import re
    if re.search(r"\b(avg|max|min|count)\s*\(", expr):
        return False
    no_nullif = re.sub(r"nullif\s*\([^()]*\)", "0", expr)
    return "/" not in no_nullif


def gen_recon_tests(inst, ctx) -> list[tuple[str, str]]:
    """方向一（勾稽护栏）：为每条 base→child 边生成守恒测试——
    父层（细粒度）按子层维度聚合后，与子层逐指标比对（可加指标严格相等，
    比率/非 sum 聚合豁免）。父层经由 carry 链携带子层指标所需的全部可加列，
    因此子层指标 expr 可在父层逐字重算。任一差异行即测试失败，diff 可读。"""
    reps, children, req, tok = ctx
    out: list[tuple[str, str]] = []
    for parent_key, kids in children.items():
        parent_cols = set(req[parent_key]) | tok[parent_key]
        for child_key in kids:
            child_rep = reps[child_key]
            shared_dims = [d for d in req[child_key] if d in set(req[parent_key])]
            if not shared_dims:
                continue
            metrics = [(m, inst.metric(m)["expr"]) for m in child_rep.get("metrics", [])
                       if _is_additive(inst.metric(m)["expr"])]
            if not metrics:
                continue
            dims_select = ", ".join(f'"{d}"' for d in shared_dims)
            dims_join = " and ".join(
                f'(p."{d}" = c."{d}" or (p."{d}" is null and c."{d}" is null))'
                for d in shared_dims)
            dims_coalesce = ", ".join(f'coalesce(p."{d}", c."{d}") as "{d}"' for d in shared_dims)
            child_agg = ", ".join(f'"{m}"' for m, _ in metrics)
            parent_agg = ", ".join(f'{expr} as "{m}"' for m, expr in metrics)
            diffs = []
            for m, _ in metrics:
                diffs.append(
                    f'select \'{m}\' as 指标, {dims_coalesce}, '
                    f'p."{m}" as 父层重算, c."{m}" as 子层值 '
                    f'from parent p full outer join child c on {dims_join} '
                    f'where abs(coalesce(p."{m}", 0) - coalesce(c."{m}", 0)) > 0.01')
            body = "\nunion all\n".join(diffs)
            sql = (f"-- 生成物：勾稽守恒测试（{child_key} ← {parent_key}；"
                   f"比率/非可加指标豁免）\n"
                   f"with child as (\n"
                   f"  select {dims_select}, {child_agg}\n"
                   f"  from {{{{ ref('mart_{child_key}') }}}}\n"
                   f"), parent as (\n"
                   f"  select {dims_select}, {parent_agg}\n"
                   f"  from {{{{ ref('mart_{parent_key}') }}}}\n"
                   f"  group by {', '.join(str(i + 1) for i in range(len(shared_dims)))}\n"
                   f")\n" + body + "\n")
            out.append((f"recon_{child_key}.sql", sql))
    return out


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
    profiles_yml = f"""# 生成物：实例 {n} 的 dbt 连接（库文件独立，实例间物理隔离；绝对路径防 CWD 漂移）
cl:
  target: {n}
  outputs:
    {n}:
      type: duckdb
      path: "{(inst.pipeline_dir / inst.db_path).resolve().as_posix()}"
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

    # 匹配契约测试 + 字段 range 契约测试
    for fname, content in gen_match_tests(inst):
        files[f"tests/{fname}"] = content
    # 勾稽护栏：base 边守恒测试（方向一）
    for fname, content in gen_recon_tests(inst, _report_graph(inst)):
        files[f"tests/{fname}"] = content
    for src in inst.sources.get("sources", []):
        for fname, content in gen_range_tests(src):
            files[f"tests/{fname}"] = content

    # marts（统一生成器：无 base 无后代的报表与旧路径字节级等价；分层/被分层报表自动升级）
    ctx = _report_graph(inst)
    for rep in inst.dashboard.get("reports", []):
        files[f"models/marts/mart_{rep['key']}.sql"] = gen_mart_model(inst, rep, ctx)
        files[f"models/marts/mart_{rep['key']}.yml"] = gen_mart_yml(inst, rep)

    # 匹配契约测试元数据（跑批收获进 raw.contract_report 统一账本）
    files["contract_tests.json"] = json.dumps(contract_test_meta(inst), ensure_ascii=False, indent=1)

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
