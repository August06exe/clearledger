# -*- coding: utf-8 -*-
"""测试 Agent 专用：对 retail/hro 每张报表做无筛选全量查询，把实际结果
按判分约定（时间列升序、非时间按维度列升序、NULL 组最后；金额 round2、比率 round4）
写入 tests/v0.4/judge/actual_<instance>.json，结构：
  {"report_key": {"columns": [...实际列名...], "rows": [...]}}

不改引擎、不读 expected/。可重复运行（幂等）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from semantic.loader import load_instance  # noqa: E402
from semantic.query import run_report  # noqa: E402

# 判分约定：比率类 round(…,4)，金额类 round(…,2)，计数/数量保持原样
RATIO_COLS = {"毛利率", "库存周转率", "电商销售占比", "回款率"}
MONEY_COLS = {"销售额", "销售成本", "毛利", "采购额", "退货额", "净采购",
              "服务费收入", "回款额", "应收余额", "人力成本",
              "人均产值", "人均人力成本"}


def round_cell(col: str, v):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return v
    if col in RATIO_COLS:
        return round(float(v), 4)
    if col in MONEY_COLS:
        return round(float(v), 2)
    # 计数/数量：整数值统一为 int，避免 12.0 与 12 的表示差异
    if float(v).is_integer():
        return int(v)
    return v


def sort_rows(columns: list[str], rows: list[dict], metric_cols: set[str]) -> list[dict]:
    """排序键 = 非指标列按列序（时间列自然在首列）；升序，NULL 最后。"""
    key_cols = [c for c in columns if c not in metric_cols]

    def key(r: dict):
        return tuple((r.get(c) is None, r.get(c)) for c in key_cols)

    return sorted(rows, key=key)


def collect(instance: str, out_path: Path) -> None:
    inst = load_instance(instance)
    out: dict = {}
    for rep in inst.dashboard.get("reports", []):
        key = rep["key"]
        rows = run_report(instance, key, filters=None, limit=500)
        columns = list(rows[0].keys()) if rows else []
        metric_cols = set(rep.get("metrics", []))
        rows = sort_rows(columns, rows, metric_cols)
        for r in rows:
            for c in columns:
                r[c] = round_cell(c, r[c])
        out[key] = {"columns": columns, "rows": rows}
        print(f"[{instance}] {key}: {len(rows)} 行, columns={columns}")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {out_path}")


if __name__ == "__main__":
    targets = sys.argv[1:] or ["retail", "hro"]
    for name in targets:
        collect(name, HERE / f"actual_{name}.json")
