# -*- coding: utf-8 -*-
"""实例摄取执行器：入口档案 + 字段契约的运行时

用法：.venv/Scripts/python -m semantic.ingest_run --instance sales

流程：文件发现（模式匹配+编码尝试）→ 有序清洗原语 → 逐字段契约校验
     → 问题策略定级 → 落 raw + raw.contract_report（违规明细留痕）
红灯语义：任一 red 级问题（文件缺失/表头变/空文件/唯一键冲突/red 字段违规）
         → 退出码 1 → 跑批红灯；yellow → 报告留痕不阻断；pending → 待处理清单记录。
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd
from pandas.errors import EmptyDataError

from semantic.loader import ROOT, ConfigError, load_instance

LEVEL_ORDER = {"red": 3, "yellow": 2, "pending": 1, "ignore": 0}


def discover_file(inbox: Path, patterns: list[str], problems: list[dict],
                  source_name: str) -> Path | None:
    """按序匹配模式；同模式多命中取 mtime 最新的一份，其余记 multi_match 黄灯留痕
    （防旧文件遮蔽新月文件——绿灯出旧数据比找不到文件更危险）"""
    for pat in patterns:
        hits = sorted(inbox.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
        if hits:
            if len(hits) > 1:
                problems.append({
                    "source": source_name, "rule": "multi_match", "level": "yellow",
                    "detail": f"模式 {pat} 命中 {len(hits)} 个文件，已取最新 {hits[0].name}（mtime），"
                              f"被忽略: {[h.name for h in hits[1:]]}"})
            return hits[0]
    return None


def read_file(path: Path, encodings: list[str], sheet: int | None = None) -> pd.DataFrame:
    last_err: Exception | None = None
    suffix = path.suffix.lower()
    if suffix == ".csv":
        if path.stat().st_size == 0:
            raise EmptyDataError(f"{path.name} 是 0 字节文件")
        for enc in encodings:
            try:
                return pd.read_csv(path, encoding=enc, dtype=str)
            except UnicodeDecodeError as e:
                last_err = e
        raise RuntimeError(f"编码尝试全部失败 {[enc for enc in encodings]}: {path.name}（{last_err}）")
    if suffix in (".xlsx", ".xls"):
        # 仅支持 xlsx（openpyxl 不读 legacy xls——xls 会显式报错而非崩溃）
        if suffix == ".xls":
            raise RuntimeError(f"{path.name} 是旧版 .xls，请另存为 .xlsx 后投放")
        return pd.read_excel(path, engine="openpyxl", dtype=str,
                             sheet_name=sheet if sheet is not None else 0)
    raise RuntimeError(f"不支持的文件类型: {path.name}")


def apply_clean(df: pd.DataFrame, steps: list[dict | str]) -> pd.DataFrame:
    """有序清洗原语管道。原语集合：trim_columns / strip_strings / drop_rows_if"""
    for step in steps:
        name = step if isinstance(step, str) else list(step.keys())[0]
        arg = {} if isinstance(step, str) else step[name]
        if name == "trim_columns":
            df.columns = [str(c).strip() for c in df.columns]
        elif name == "strip_strings":
            for c in df.columns:
                # pandas 3 的字符串列是 StringDtype 而非 object——两种都判，.str.strip() 均适用
                if df[c].dtype == object or str(df[c].dtype) in ("string", "str"):
                    df[c] = df[c].str.strip()
                    df[c] = df[c].replace({"": None})
        elif name == "drop_rows_if":
            col, op = arg["col"], arg["op"]
            if col not in df.columns:
                continue
            if op == "is_null":
                df = df[df[col].notna()]
        else:
            raise RuntimeError(f"未知清洗原语: {name}")
    return df


def _check_range(series, rng):
    lo, hi = rng
    v = pd.to_numeric(series, errors="coerce")
    return (~v.between(lo, hi)) & v.notna()


def validate_and_transform(df: pd.DataFrame, fields: list[dict], source_name: str,
                           violations: list[dict]) -> pd.DataFrame:
    """逐字段契约校验 + 类型化。前置条件：df 已按字段契约 rename 为英文列名（map）。
    违规记录进 violations（不阻断，按级别汇总定级）；类型化同步完成（date/integer/decimal）。"""
    for f in fields:
        col, typ = f["map"], f.get("type", "string")
        level = f.get("level", "yellow")
        if col not in df.columns:
            continue  # 表头级问题已在 header_changed 处理

        s = df[col]
        # 类型化 + 转换失败统计
        if typ == "date":
            t = pd.to_datetime(s, errors="coerce")
            bad = int(t.isna().sum() - s.isna().sum())
        elif typ in ("integer", "decimal"):
            t = pd.to_numeric(s, errors="coerce")
            bad = int(t.isna().sum() - s.isna().sum())
        else:
            t = s
            bad = 0
        if bad:
            violations.append({"source": source_name, "field": col, "rule": "type_coerce",
                               "level": level, "count": bad,
                               "sample": str(s[t.isna()].dropna().iloc[:3].tolist())})
            df[col] = t
        else:
            df[col] = t

        cur = df[col]
        # required：缺失行剔除（计数留痕）
        if f.get("required"):
            n = int(cur.isna().sum())
            if n:
                violations.append({"source": source_name, "field": col, "rule": "required_missing_dropped",
                                   "level": level, "count": n, "sample": ""})
                df = df[cur.notna()]
                cur = df[col]
        # 缺失策略
        if f.get("missing") == "default" and "default" in f:
            df[col] = cur.fillna(f["default"])
            cur = df[col]
        # range
        if f.get("range") and typ in ("integer", "decimal"):
            mask = _check_range(cur, f["range"])
            if mask.any():
                violations.append({"source": source_name, "field": col, "rule": "range",
                                   "level": level, "count": int(mask.sum()),
                                   "sample": str(cur[mask].iloc[:3].tolist())})
        # enum
        if f.get("enum"):
            mask = cur.notna() & (~cur.isin(f["enum"]))
            if mask.any():
                violations.append({"source": source_name, "field": col, "rule": "enum",
                                   "level": level, "count": int(mask.sum()),
                                   "sample": str(sorted(set(cur[mask].dropna()))[:5])})
        # format 正则
        if f.get("format"):
            mask = cur.notna() & (~cur.astype(str).str.match(f["format"]))
            if mask.any():
                violations.append({"source": source_name, "field": col, "rule": "format",
                                   "level": level, "count": int(mask.sum()),
                                   "sample": str(cur[mask].iloc[:3].tolist())})
        # unique（唯一键冲突 = 数据损坏，恒 red——双计收入风险）
        if f.get("unique"):
            dup = int(cur.duplicated(keep=False).sum())
            if dup:
                violations.append({"source": source_name, "field": col, "rule": "unique",
                                   "level": "red", "count": dup,
                                   "sample": str(cur[cur.duplicated(keep=False)].unique()[:3].tolist())})
    return df


def ingest_source(con, inst, src: dict, inbox: Path, run_id: str,
                  violations: list[dict], problems: list[dict]) -> dict:
    name, title = src["name"], src.get("title", src["name"])
    disc = src.get("discover", {})
    path = discover_file(inbox, disc.get("patterns", [f"{name}.*"]), problems, name)

    def problem(rule: str, level: str, detail: str):
        problems.append({"source": name, "rule": rule, "level": level, "detail": detail})

    if path is None:
        problem("file_missing", src.get("problems", {}).get("file_missing", "red"),
                f"投放区 {inbox} 未匹配 {disc.get('patterns')}")
        return {"source": name, "status": "error", "error": "file_missing"}

    try:
        df = read_file(path, disc.get("encodings", ["utf-8-sig"]), disc.get("sheet"))
    except (EmptyDataError, RuntimeError) as e:
        problem("read_failed", "red", f"{path.name} 读取失败: {e}")
        return {"source": name, "status": "error", "error": f"read_failed: {e}"}
    raw_rows = len(df)
    if raw_rows == 0:
        problem("empty_file", src.get("problems", {}).get("empty_file", "red"), f"{path.name} 为空文件")
        return {"source": name, "status": "error", "error": "empty_file"}
    df = apply_clean(df, src.get("clean", []))
    if disc.get("skip_rows"):
        df = df.iloc[disc["skip_rows"]:]

    fields = src.get("fields", [])
    col_map = {f["cn"]: f["map"] for f in fields}
    missing_headers = [f["cn"] for f in fields if f["cn"] not in df.columns]
    if missing_headers:
        problem("header_changed", src.get("problems", {}).get("header_changed", "red"),
                f"{path.name} 缺少声明的列: {missing_headers}")
        return {"source": name, "status": "error", "error": f"header_changed:{missing_headers}"}

    df = df.rename(columns=col_map)
    keep = [f["map"] for f in fields] + ["_source_file", "_loaded_at"]
    for extra in ("_source_file", "_loaded_at"):
        if extra not in df.columns:
            df[extra] = path.name if extra == "_source_file" else datetime.now().isoformat(timespec="seconds")
    df = df[keep]

    before = len(df)
    df = validate_and_transform(df, fields, name, violations)
    dropped = before - len(df)

    if len(df) == 0:
        problem("empty_after_clean", src.get("problems", {}).get("empty_after_clean", "red"),
                f"{path.name} 清洗/契约剔除后为 0 行（原始 {raw_rows} 行）")
        return {"source": name, "status": "error", "error": "empty_after_clean"}

    ratio_cfg = src.get("problems", {}).get("row_drop_ratio")
    if ratio_cfg and raw_rows and dropped / raw_rows > ratio_cfg["max"]:
        problem("row_drop_ratio", ratio_cfg.get("level", "yellow"),
                f"剔行 {dropped}/{raw_rows} = {dropped / raw_rows:.1%} 超过阈值 {ratio_cfg['max']:.1%}")

    coerce_cfg = src.get("problems", {}).get("type_coerce_ratio")
    if coerce_cfg:
        n_bad = sum(v["count"] for v in violations
                    if v["source"] == name and v["rule"] == "type_coerce")
        if raw_rows and n_bad / raw_rows > coerce_cfg["max"]:
            problem("type_coerce_ratio", coerce_cfg.get("level", "yellow"),
                    f"类型转换失败 {n_bad}/{raw_rows} 超过阈值 {coerce_cfg['max']:.1%}")

    con.register("df_view", df)
    con.execute(f'create or replace table raw."{name}" as select * from df_view')
    con.unregister("df_view")
    return {"source": name, "file": path.name, "rows": len(df), "dropped": dropped, "status": "ok"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True)
    args = ap.parse_args()

    try:
        inst = load_instance(args.instance)
    except ConfigError as e:
        print(f"[config] {e}", file=sys.stderr)
        return 2

    db_file = (inst.pipeline_dir / inst.db_path).resolve()
    db_file.parent.mkdir(parents=True, exist_ok=True)

    last: Exception | None = None
    con = None
    for _ in range(20):
        try:
            con = duckdb.connect(str(db_file))
            break
        except duckdb.IOException as e:
            last = e
            time.sleep(0.5)
    if con is None:
        print(f"[fail] 仓库被占用: {last}", file=sys.stderr)
        return 1

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    violations: list[dict] = []
    problems: list[dict] = []
    results: list[dict] = []
    try:
        con.execute("create schema if not exists raw")
        for src in inst.sources.get("sources", []):
            try:
                r = ingest_source(con, inst, src, inst.inbox, run_id, violations, problems)
            except Exception as e:  # N-02：单源崩溃不得拖垮整轮——留痕后继续处理其他源
                problems.append({"source": src.get("name"), "rule": "ingest_crashed", "level": "red",
                                 "detail": f"{type(e).__name__}: {e}"})
                r = {"source": src.get("name"), "status": "error", "error": f"crashed: {e}"}
            results.append(r)
            tag = "ok" if r["status"] == "ok" else "FAIL"
            print(f"  [{tag}] {r['source']:22s} {r.get('file', '-'):28s} {r.get('rows', '-')} 行")

        # 契约报告留痕
        con.execute("""create table if not exists raw.contract_report (
            run_id varchar, ts timestamp, source varchar, field varchar,
            rule varchar, level varchar, cnt bigint, sample varchar)""")
        for v in violations:
            con.execute("insert into raw.contract_report values (?,?,?,?,?,?,?,?)",
                        [run_id, datetime.now(), v["source"], v["field"], v["rule"], v["level"],
                         v["count"], v.get("sample", "")[:200]])
        for p in problems:
            con.execute("insert into raw.contract_report values (?,?,?,?,?,?,?,?)",
                        [run_id, datetime.now(), p["source"], "-", p["rule"], p["level"], 0,
                         p["detail"][:200]])
    finally:
        con.close()

    has_red = any(p["level"] == "red" for p in problems) or any(v["level"] == "red" for v in violations)
    pendings = [v for v in violations if v["level"] == "pending"]

    report = {
        "instance": inst.name, "run_id": run_id,
        "started_at": run_id, "ok": not has_red,
        "results": results, "problems": problems, "violations": violations,
        "pending_count": len(pendings),
    }
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / f"logs/ingest_{inst.name}_last.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    print(f"摄取完成: {'RED' if has_red else 'OK'} | 违规 {len(violations)} 项"
          f"（yellow {sum(1 for v in violations if v['level'] == 'yellow')} / "
          f"red {sum(1 for v in violations if v['level'] == 'red')} / "
          f"pending {len(pendings)}）")
    return 1 if has_red else 0


if __name__ == "__main__":
    sys.exit(main())
