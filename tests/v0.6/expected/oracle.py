# -*- coding: utf-8 -*-
"""独立口径 oracle —— tests/v0.6 密封答案计算器（**v2，R2 重密封版**）。

纪律（tri-agent-testing oracle-grader.md 第一节）：
  - 绝不 import 被测系统任何模块（semantic/ app/ ops/ 一概不碰）；
  - 只用 pandas + PyYAML + 标准库，从 instances/_wb_r1/ 的 CSV 与 YAML 现算；
  - 确定性：无随机、无时间戳，重复运行 answer.json 逐字节一致；
  - 契约语义依据：docs/设计-v0.5-配置工作台.md §3.5/§3.6 + docs/待确认与决策.md D15
    + R1 判分归因裁定（2026-09-21，六条引擎侧修复/裁定，见 assumptions）。

R2 语义变更（相对 v1，依据 R1 裁定）：
  1. 契约校验两阶段 v2：先在原始帧全量记录违规、后统一剔行——type 行不再被剔行逻辑吞掉；
  2. type 违规行保留（置 NULL 交由 missing 策略），不剔除；
  3. required 违规行在摄取层剔除（"入库即干净字段"）；
  4. raw 行数 = 文件数据行数 − 该源 required 剔行数（v1 的"raw=文件镜像"作废）；
  5. 匹配契约行写入 contract_report：source = wide.yml 声明名（本实例 wide_ledger），
     field = join 左键；cnt = dbt 测试 failures 数——null_match 测试为 select distinct，
     cnt = 去重后未匹配左键值数（空串算一个值，幽灵键算一个值）；fanout cnt = 去重后
     重复右键数；
  6. join 物理扩行语义不变：宽表行数 = 保留主表行数 + 扇出扩行数。

运行（仓库根目录）：
    .venv/Scripts/python.exe tests/v0.6/expected/oracle.py
输出：本文件同目录 answer.json（UTF-8、LF、ensure_ascii=False、sort_keys）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[3]
INST = REPO / "instances" / "_wb_r1"
OUT = Path(__file__).resolve().parent / "answer.json"

ANSWER_VERSION = 2


def load_source_csv(sname: str, src_cfg: dict) -> pd.DataFrame:
    """按 discover.patterns 读唯一命中文件（dtype=str、空串不转 NaN，保真口径）。"""
    hits = sorted(INST.glob("data/inbox/" + src_cfg["discover"]["patterns"][0]))
    if len(hits) != 1:
        raise SystemExit(f"源 {sname} 命中 {len(hits)} 个文件，基线约定单文件")
    return pd.read_csv(hits[0], dtype=str, keep_default_na=False, encoding="utf-8-sig")


def apply_column_map(df: pd.DataFrame, fields: list, sname: str) -> pd.DataFrame:
    """入口档案列映射：中文表头 cn → 英文字段 map（独立实现）。"""
    cn2map = {f["cn"]: f["map"] for f in fields}
    missing = [c for c in cn2map if c not in df.columns]
    if missing:
        raise SystemExit(f"{sname}: 表头缺列 {missing}（header_changed 应为 red，基线不播种）")
    return df.rename(columns=cn2map)


def coercible(v: str, typ: str) -> bool:
    """类型可转判定（独立实现，不依赖引擎）。空值不参与类型判定（A7 由调用方保证）。"""
    try:
        x = float(v)
    except ValueError:
        return False
    if typ == "integer":
        return float(x).is_integer()
    return True  # decimal/string


def field_contract_rows(sname: str, df: pd.DataFrame, fields: list) -> tuple[list[dict], pd.DataFrame, int]:
    """字段契约逐条评估（两阶段 v2：原始帧全量记录 → 统一剔行）。

    - required 空值：记录 rule=required，该行剔除（裁定 3）；
    - type 不可强转：记录 rule=type，行保留置 NULL（裁定 2）；
    - enum/range/missing 策略同 v1（软记录不剔行 / 空值跳过 / 缺失默认零行）。
    返回 (投影行, 剔行后保留帧, required 剔行数)。
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
                drop_mask |= s == ""                                    # 剔行（裁定 3）
        if "enum" in f:
            allowed = set(map(str, f["enum"]))
            bad = nonempty & ~s.isin(allowed)                           # 空值跳过（A7）
            n = int(bad.sum())
            if n:
                out.append(dict(source=sname, field=col, rule="enum", level=f.get("level", "yellow"), cnt=n))
        if "range" in f:
            lo, hi = f["range"]
            num = pd.to_numeric(s.where(nonempty), errors="coerce")
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
                    # v2：type 行保留置 NULL（裁定 2），不再进 drop_mask
        # missing=default（A6）：缺失策略补默认值，零契约行 —— 显式不产出
        # unique：本账套未声明（右表键重复属 join 扇出语义），不产出
    required_drops = 0
    for f in fields:
        if f.get("required") and f.get("level") and f["map"] in df.columns:
            required_drops += int((df[f["map"]].str.strip() == "").sum())
    return out, df[~drop_mask], required_drops


def main() -> int:
    if not INST.is_dir():
        print("缺少 instances/_wb_r1 —— 先运行 python tests/v0.6/generate.py", file=sys.stderr)
        return 2
    cfg = {n: yaml.safe_load((INST / f"{n}.yml").read_text(encoding="utf-8"))
           for n in ["sources", "wide", "dimensions", "metrics", "dashboard"]}

    srcs = {s["name"]: s for s in cfg["sources"]["sources"]}
    dfs: dict[str, pd.DataFrame] = {}
    file_rows: dict[str, int] = {}
    raw_rows: dict[str, int] = {}
    proj: list[dict] = []
    kept_main: pd.DataFrame | None = None

    for sname in ["fact_ledger", "stock_snapshot", "stores", "products", "suppliers"]:
        df = load_source_csv(sname, srcs[sname])
        df = apply_column_map(df, srcs[sname]["fields"], sname)
        dfs[sname] = df
        file_rows[sname] = int(len(df))
        rows, kept, req_drops = field_contract_rows(sname, df, srcs[sname]["fields"])
        proj += rows
        raw_rows[sname] = int(len(df)) - req_drops                    # 裁定 4：raw = 文件 − required 剔行
        if sname == "fact_ledger":
            kept_main = kept

    # ---- 匹配契约（裁定 5）：cnt = dbt failures = 去重键数 ----
    wide = cfg["wide"]["wide"]
    wide_name = wide["name"]
    extra = 0
    for j in wide["joins"]:
        right = dfs[j["table"]]
        lkey, rkey = j["keys"]["left"], j["keys"]["right"]
        dup_keys = set(right[rkey][right[rkey].duplicated()])
        if dup_keys:                                   # fanout：去重后重复右键数
            n = len(dup_keys)
            proj.append(dict(source=wide_name, field=lkey, rule="fanout",
                             level=j["contract"]["fanout"], cnt=n))
            left_rows = int(kept_main[lkey].isin(dup_keys).sum())
            extra += left_rows                          # 物理扩行仍按受影响左行数
        right_keys = set(right[rkey])
        lv = kept_main[lkey].str.strip()
        unmatched = kept_main[lkey][(lv == "") | ~lv.isin(right_keys)]
        if len(unmatched):                              # null_match：去重后未匹配左键值数
            n = int(unmatched.nunique())
            proj.append(dict(source=wide_name, field=lkey, rule="null_match",
                             level=j["contract"]["null_match"], cnt=n))
        # orphan_right: ignore —— 右表孤儿不产出
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
        "answer_version": ANSWER_VERSION,
        "instance": "_wb_r1",
        "pending": {
            "projection": "(source, field, rule, level, cnt)，集合无序比对；sample 仅要求非空",
            "items": proj,
        },
        "impact": {"metrics": impact_metrics, "dimensions": impact_dims},
        "rows": {
            "files": file_rows,
            "raw": {f"raw.{k}": v for k, v in raw_rows.items()},     # 裁定 4
            "wide_ledger": wide_rows,                                 # 裁定 4/5 + 物理扩行
        },
        "assumptions_applied": {
            "pending.items": ["A1", "A2", "A3v2", "A4", "A6", "A7", "A8", "A9v2"],
            "rows.raw": ["A4", "A5v2"],
            "rows.wide_ledger": ["A3v2", "A4", "A9v2"],
        },
    }
    OUT.write_text(json.dumps(answer, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"[OK] answer.json (v{ANSWER_VERSION}) -> {OUT}")
    for r in proj:
        print("   ", r)
    print(f"    rows: files={file_rows} raw={raw_rows} wide={wide_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
