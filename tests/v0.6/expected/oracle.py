# -*- coding: utf-8 -*-
"""独立口径 oracle —— tests/v0.6 密封答案计算器。

纪律（tri-agent-testing oracle-grader.md 第一节）：
  - 绝不 import 被测系统任何模块（semantic/ app/ ops/ 一概不碰）；
  - 只用 pandas + PyYAML + 标准库，从 instances/_wb_r1/ 的 CSV 与 YAML 现算；
  - 确定性：无随机、无时间戳，重复运行 answer.json 逐字节一致；
  - 契约语义依据：docs/设计-v0.5-配置工作台.md §3.5/§3.6 + docs/待确认与决策.md D15
    （数据契约三层：入口档案/字段契约/匹配契约，级别由配置定级）。

运行（仓库根目录）：
    .venv/Scripts/python.exe tests/v0.6/expected/oracle.py
输出：本文件同目录 answer.json（UTF-8、LF、ensure_ascii=False、sort_keys）。

与引擎可能分歧的假设（逐条同步记录在 caliber.json 的 assumptions，判分归因用）：
  A1 level 字面量：contract_report.level = 配置声明的级别字符串（yellow/red）；
     设计文档 §3.5 示例中的 "pending" 视为示意值。
  A2 软违规（enum/range/unique/null_match/fanout）记录不剔行，行照常入库/入宽表。
  A3 类型不可强转 → 记 rule=type 一行且该行被剔除。
  A4 required 空值 → 记 rule=required 一行且该行被剔除。
  A5 raw 层为源文件镜像（手册红线"原始层只增不改"）：raw 行数 = 文件数据行数。
  A6 missing=default 为缺失策略而非违规：补默认值、不产生契约行。
  A7 空值跳过 enum/range 检查（retail 真实基线佐证：海量空供应商编码未产生枚举/范围行）。
  A8 join 契约行记在宽表名下（source=wide.name），field=左表键列名。
  A9 fanout 物理扩行：cnt=受影响的左表行数；宽表行数 = 保留主表行数 + 扩行数。
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[3]
INST = REPO / "instances" / "_wb_r1"
OUT = Path(__file__).resolve().parent / "answer.json"


def load_source_csv(sname: str, src_cfg: dict) -> pd.DataFrame:
    """按 discover.patterns 读唯一命中文件（dtype=str、空串不转 NaN，保真镜像口径）。"""
    hits = sorted(INST.glob("data/inbox/" + src_cfg["discover"]["patterns"][0]))
    if len(hits) != 1:
        raise SystemExit(f"源 {sname} 命中 {len(hits)} 个文件，基线约定单文件")
    return pd.read_csv(hits[0], dtype=str, keep_default_na=False, encoding="utf-8-sig")


def coercible(v: str, typ: str) -> bool:
    """类型可转判定（独立实现，不依赖引擎）。空值不参与类型判定（A7 由调用方保证）。"""
    try:
        x = float(v)
    except ValueError:
        return False
    if typ == "integer":
        return float(x).is_integer()
    return True  # decimal/string


def apply_column_map(df: pd.DataFrame, fields: list, sname: str) -> pd.DataFrame:
    """入口档案列映射：中文表头 cn → 英文字段 map（独立实现）。"""
    cn2map = {f["cn"]: f["map"] for f in fields}
    missing = [c for c in cn2map if c not in df.columns]
    if missing:
        raise SystemExit(f"{sname}: 表头缺列 {missing}（header_changed 应为 red，基线不播种）")
    return df.rename(columns=cn2map)


def field_contract_rows(sname: str, df: pd.DataFrame, fields: list) -> list[dict]:
    """字段契约逐条评估 → 稳定投影行（A2 软违规不剔行、A3/A4 剔行、A6 缺失策略零行、A7 空值跳过）。

    入参 df 已应用列映射。
    """
    out: list[dict] = []
    drop_mask = pd.Series(False, index=df.index)
    for f in fields:
        col = f["map"]
        if col not in df.columns:
            raise SystemExit(f"{sname}.{f['cn']}: 列缺失（header_changed 应为 red，基线不播种）")
        s = df[col].str.strip()
        nonempty = s != ""
        if f.get("required") and f.get("level"):
            n = int((s == "").sum())
            if n:
                out.append(dict(source=sname, field=col, rule="required", level=f["level"], cnt=n))
                drop_mask |= s == ""                                   # A4
        if "enum" in f:
            allowed = set(map(str, f["enum"]))
            bad = nonempty & ~s.isin(allowed)                          # A7
            n = int(bad.sum())
            if n:
                out.append(dict(source=sname, field=col, rule="enum", level=f.get("level", "yellow"), cnt=n))
        if "range" in f:
            lo, hi = f["range"]
            num = pd.to_numeric(s.where(nonempty), errors="coerce")    # A7：空值跳过
            bad = nonempty & num.notna() & ((num < lo) | (num > hi))
            n = int(bad.sum())
            if n:
                out.append(dict(source=sname, field=col, rule="range", level=f.get("level", "yellow"), cnt=n))
        if "type" in f and f.get("level"):
            typ = f["type"]
            if typ in ("integer", "decimal"):
                bad = nonempty & ~s.map(lambda v: coercible(v, typ))
                n = int(bad.sum())
                if n:
                    out.append(dict(source=sname, field=col, rule="type", level=f["level"], cnt=n))
                    drop_mask |= bad                                    # A3
        # missing=default（A6）：缺失策略，补默认值，零契约行 —— 显式不产出
        # unique：本账套未声明（SCD 形态 + 右表键重复属 join 扇出语义），通用实现略
    kept = df[~drop_mask]
    return out, kept


def main() -> int:
    if not INST.is_dir():
        print("缺少 instances/_wb_r1 —— 先运行 python tests/v0.6/generate.py", file=sys.stderr)
        return 2
    cfg = {n: yaml.safe_load((INST / f"{n}.yml").read_text(encoding="utf-8"))
           for n in ["sources", "wide", "dimensions", "metrics", "dashboard"]}

    srcs = {s["name"]: s for s in cfg["sources"]["sources"]}
    dfs: dict[str, pd.DataFrame] = {}
    file_rows: dict[str, int] = {}
    proj: list[dict] = []
    kept_main: pd.DataFrame | None = None

    for sname in ["fact_ledger", "stock_snapshot", "stores", "products", "suppliers"]:
        df = load_source_csv(sname, srcs[sname])
        df = apply_column_map(df, srcs[sname]["fields"], sname)
        dfs[sname] = df
        file_rows[sname] = int(len(df))
        rows, kept = field_contract_rows(sname, df, srcs[sname]["fields"])
        proj += rows
        if sname == "fact_ledger":
            kept_main = kept

    # ---- 匹配契约（A8/A9）：独立模拟 left join 的扇出与匹空 ----
    wide = cfg["wide"]["wide"]
    extra = 0
    for j in wide["joins"]:
        right = dfs[j["table"]]
        lkey, rkey = j["keys"]["left"], j["keys"]["right"]
        dup_keys = set(right[rkey][right[rkey].duplicated()])
        if dup_keys:                                   # fanout：受影响左行数（A9）
            n = int(kept_main[lkey].isin(dup_keys).sum())
            if n:
                proj.append(dict(source=wide["name"], field=lkey, rule="fanout",
                                 level=j["contract"]["fanout"], cnt=n))
            extra += n
        nulls = int((kept_main[lkey].str.strip() == "").sum())   # null_match：空键左行数（A2）
        if nulls:
            proj.append(dict(source=wide["name"], field=lkey, rule="null_match",
                             level=j["contract"]["null_match"], cnt=nulls))
        # orphan_right: ignore —— 右表孤儿零行（A2 族：配置定级 ignore，不产出）
    wide_rows = int(len(kept_main)) + extra

    proj.sort(key=lambda r: (r["source"], r["field"], r["rule"]))

    # ---- 影响预览（设计 §3.6：纯配置推导，与引擎无关） ----
    reports = cfg["dashboard"]["reports"]
    metric_names = [m["name"] for m in cfg["metrics"]["metrics"]]
    dim_names = [d["name"] for d in cfg["dimensions"]["dimensions"]]
    impact_metrics = {
        m: sorted(r["key"] for r in reports if m in r["metrics"]) for m in metric_names
    }
    impact_dims = {}
    for d in dim_names:
        keys = set()
        for r in reports:
            if r.get("dimension") == d or r.get("time_dim") == d or d in (r.get("filters") or []):
                keys.add(r["key"])
        impact_dims[d] = sorted(keys)

    answer = {
        "instance": "_wb_r1",
        "pending": {
            "projection": "(source, field, rule, level, cnt)，集合无序比对；sample 仅要求非空",
            "items": proj,
        },
        "impact": {"metrics": impact_metrics, "dimensions": impact_dims},
        "rows": {
            "files": file_rows,
            "raw": {f"raw.{k}": v for k, v in file_rows.items()},   # A5 镜像
            "wide_ledger": wide_rows,                                # A9
        },
        "assumptions_applied": {
            "pending.items": ["A1", "A2", "A3", "A4", "A6", "A7", "A8", "A9"],
            "rows.raw": ["A5"],
            "rows.wide_ledger": ["A2", "A3", "A4", "A9"],
        },
    }
    OUT.write_text(json.dumps(answer, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"[OK] answer.json -> {OUT}")
    for r in proj:
        print("   ", r)
    print(f"    rows: files={file_rows} wide={wide_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
