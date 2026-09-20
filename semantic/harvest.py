# -*- coding: utf-8 -*-
"""匹配契约违规收获（CLI 入口）

门户跑批链在 dbt build 后自动收获（app/services/dbt_runner._harvest_match_contracts）；
本模块给 CLI 跑批（点火指南三步链）等价能力，使挂起队列覆盖匹配契约：

    python -m semantic.harvest --instance <账套>

run_id 归属：优先沿用契约表里已有的最大 run_id（当前批次的摄取身份）；
契约表为空时回退 logs/ingest_<账套>_last.json 的 run_id；再退则用当前时间戳。
收获失败（无 sidecar / 无 run_results / 全部通过）以退出码 0 静默成功——
治理数据缺失不影响跑批结论。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import duckdb

from semantic.loader import load_instance


def harvest(inst_name: str) -> int:
    inst = load_instance(inst_name)
    sidecar = inst.pipeline_dir / "contract_tests.json"
    rr = inst.pipeline_dir / "target" / "run_results.json"
    if not sidecar.exists() or not rr.exists():
        print(f"[harvest] {inst_name}: 无 contract_tests.json 或 run_results.json，跳过")
        return 0
    metas = {m["test"]: m for m in json.loads(sidecar.read_text(encoding="utf-8"))}
    results = json.loads(rr.read_text(encoding="utf-8")).get("results", [])

    rows = []
    for r in results:
        uid = r.get("unique_id", "")
        name = uid.split(".")[-1] if uid.startswith("test.") else ""
        if name not in metas:
            continue
        st = r.get("status")
        if st == "pass":
            continue
        m = metas[name]
        level = "red" if st in ("fail", "error", "runtime error") else "yellow"
        rows.append((m["wide"], m["field"], m["rule"], level,
                     int(r.get("failures") or 0),
                     str(r.get("message") or f"匹配契约 {m['rule']} 命中 {m['field']}")[:200]))
    if not rows:
        print(f"[harvest] {inst_name}: 匹配契约测试全部通过，无违规可收获")
        return 0

    db = (inst.pipeline_dir / inst.db_path).resolve()
    con = duckdb.connect(str(db))
    try:
        con.execute("""create table if not exists raw.contract_report (
            run_id varchar, ts timestamp, source varchar, field varchar,
            rule varchar, level varchar, cnt bigint, sample varchar)""")
        prior = con.execute("select max(run_id) from raw.contract_report").fetchone()[0]
        run_id = prior or _fallback_run_id(inst)
        con.executemany(
            "insert into raw.contract_report values (?,?,?,?,?,?,?,?)",
            [(run_id, datetime.now(), w, f, r, lv, c, smp)[:8]
             for (w, f, r, lv, c, smp) in rows])
    finally:
        con.close()
    print(f"[harvest] {inst_name}: 匹配契约违规 {len(rows)} 行 → raw.contract_report（run_id={run_id}）")
    return 0


def _fallback_run_id(inst) -> str:
    last = inst.pipeline_dir.parent / ".." / "logs" / f"ingest_{inst.name}_last.json"
    try:
        return json.loads(last.read_text(encoding="utf-8")).get("run_id") or \
            datetime.now().strftime("%Y%m%d_%H%M%S")
    except Exception:
        return datetime.now().strftime("%Y%m%d_%H%M%S")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", required=True)
    args = ap.parse_args()
    return harvest(args.instance)


if __name__ == "__main__":
    raise SystemExit(main())
