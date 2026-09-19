# -*- coding: utf-8 -*-
"""明账 ClearLedger — 开放 MCP 只读接口（v0.4）

让外部 AI agent（claude code / zcode / hermes / codex 等 MCP 客户端）以只读方式
接入明账：问数（指标目录/报表查询）、诊断（跑批状态/缺什么数据）、查口径。

安全边界（设计承诺）：
- 只读：不暴露任何写操作
- 只能查"已声明的维度×指标"——汇总级出网由架构保证，结构性摸不到明细行
- 每次工具调用留痕 logs/mcp_audit.jsonl（谁/何时/查了什么/结果规模）

接入方式（stdio）——在 MCP 客户端配置：
  command: <仓库>/.venv/Scripts/python.exe
  args: [<仓库>/mcp_server.py]
详见 docs/AI-操作手册.md R-10。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from semantic import query as semantic_query
from semantic.loader import ConfigError, load_instance
from semantic.loader import list_instances as _loader_list_instances

AUDIT = ROOT / "logs" / "mcp_audit.jsonl"

mcp = FastMCP("clearledger")


def _audit(tool: str, args: dict, result_size: str) -> None:
    """审计留痕：每次工具调用一行 JSONL。失败不阻断工具本身。"""
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "tool": tool, "args": {k: str(v)[:80] for k, v in args.items()},
                "result": result_size,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _inst(name: str | None) -> str:
    """账套解析：未指定时用门户当前账套（settings.instance）"""
    if name:
        if name not in _loader_list_instances():
            raise ValueError(f"账套不存在: {name}（可用: {list_instances()}）")
        return name
    try:
        cur = json.loads((ROOT / "data" / "settings.json").read_text(encoding="utf-8")).get("instance")
        if cur in list_instances():
            return cur
    except Exception:
        pass
    return _loader_list_instances()[0] if _loader_list_instances() else "sales"


@mcp.tool()
def list_instances() -> str:
    """列出全部公司账套及其最近跑批状态（灯色/时间）。"""
    out = []
    for n in _loader_list_instances():
        run = None
        hf = ROOT / "data" / "runs" / f"history_{n}.json"
        if hf.exists():
            try:
                runs = json.loads(hf.read_text(encoding="utf-8"))
                run = runs[0] if runs else None
            except Exception:
                pass
        title = n
        try:
            title = load_instance(n).title
        except ConfigError:
            pass
        out.append({"name": n, "title": title,
                    "status": (run or {}).get("status", "unknown"),
                    "last_run": (run or {}).get("finished_at")})
    _audit("list_instances", {}, f"{len(out)} instances")
    return json.dumps(out, ensure_ascii=False, indent=1)


@mcp.tool()
def list_metrics(instance: str = "") -> str:
    """列出某账套的全部指标目录：名称 / 计算公式 / 中文口径说明。问数前先看这个。"""
    inst_name = _inst(instance or None)
    inst = load_instance(inst_name)
    metrics = [{"name": m["name"], "expr": m.get("expr", ""),
                "desc": m.get("desc", ""), "format": m.get("format")}
               for m in inst.metrics]
    _audit("list_metrics", {"instance": inst_name}, f"{len(metrics)} metrics")
    return json.dumps({"instance": inst_name, "title": inst.title, "metrics": metrics},
                      ensure_ascii=False, indent=1)


@mcp.tool()
def query_report(instance: str, report: str, filters: dict | None = None, limit: int = 500) -> str:
    """查询一张管理报表：只允许查该账套 dashboard 中已声明的报表，
    筛选值只允许该维度已有值（白名单）。返回汇总级数据（无明细行）。
    报表 key 与筛选维度可用 list_reports 工具查看。"""
    inst_name = _inst(instance or None)
    reps = {r["key"]: r for r in semantic_query.list_reports(inst_name)}
    if report not in reps:
        raise ValueError(f"报表不存在: {report}（可用: {sorted(reps)}）")
    rows = semantic_query.run_report(inst_name, report, filters=filters or {}, limit=min(max(int(limit), 1), 5000))
    _audit("query_report", {"instance": inst_name, "report": report, "filters": filters or {}},
           f"{len(rows)} rows")
    return json.dumps({"instance": inst_name, "report": report,
                       "columns": list(rows[0].keys()) if rows else [],
                       "rows": rows, "count": len(rows)},
                      ensure_ascii=False, indent=1, default=str)


@mcp.tool()
def list_reports(instance: str = "") -> str:
    """列出某账套的全部报表：key / 标题 / 维度 / 可用筛选维度 / 指标清单。"""
    inst_name = _inst(instance or None)
    reps = semantic_query.list_reports(inst_name)
    _audit("list_reports", {"instance": inst_name}, f"{len(reps)} reports")
    return json.dumps([{"key": r["key"], "title": r["title"], "dimension": r["dimension"],
                        "time_dim": r.get("time_dim"), "filters": r.get("filters") or [],
                        "metrics": r.get("metrics", [])} for r in reps],
                      ensure_ascii=False, indent=1)


@mcp.tool()
def get_data_status(instance: str = "") -> str:
    """数据健康诊断：最近跑批状态（绿/黄/红）、各数据源最近摄取行数、
    契约违规与告警明细——回答"新一期报表为什么没出/差什么没导入"。"""
    inst_name = _inst(instance or None)
    inst = load_instance(inst_name)
    hf = ROOT / "data" / "runs" / f"history_{inst_name}.json"
    last = None
    if hf.exists():
        try:
            runs = json.loads(hf.read_text(encoding="utf-8"))
            last = runs[0] if runs else None
        except Exception:
            pass
    missing = []
    try:
        cfg = inst.sources.get("sources", [])
        inbox = inst.inbox
        for src in cfg:
            if not any(any(inbox.glob(pat)) for pat in
                       src.get("discover", {}).get("patterns", [f"{src['name']}.*"])):
                missing.append(src["name"])
    except Exception:
        pass
    ingest_report = None
    try:
        ingest_report = json.loads(
            (ROOT / "logs" / f"ingest_{inst_name}_last.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    src_rows = [{"source": r["source"], "rows": r.get("rows"),
                 "status": r.get("status", "error")} for r in (ingest_report or {}).get("results", [])]
    out = {
        "instance": inst_name,
        "last_run": {"run_id": (last or {}).get("run_id"), "status": (last or {}).get("status"), "finished_at": (last or {}).get("finished_at"),
                     "error": (last or {}).get("error"), "counts": (last or {}).get("counts")},
        "missing_files": missing,            # 声明了但投放区找不到的源 → 这期跑不出的直接原因
        "last_ingest": src_rows,
        "violations": (ingest_report or {}).get("violations", [])[:20],
        "verdict": ("健康" if (last or {}).get("status") == "green" else
                    "有数据质量告警（黄）" if (last or {}).get("status") == "yellow" else
                    f"跑批失败（红）：{(last or {}).get('error') or '见日志'}" if last else
                    "该账套尚未跑过批"),
    }
    _audit("get_data_status", {"instance": inst_name}, f"missing={len(missing)}")
    return json.dumps(out, ensure_ascii=False, indent=1, default=str)


@mcp.tool()
def get_caliber(instance: str, metric: str) -> str:
    """查单个指标的口径：计算公式 / 中文业务说明 / 所属报表。回答"这个数怎么算的"。"""
    inst_name = _inst(instance or None)
    inst = load_instance(inst_name)
    m = next((x for x in inst.metrics if x["name"] == metric), None)
    if m is None:
        raise ValueError(f"指标不存在: {metric}（可用: {[x['name'] for x in inst.metrics]}）")
    used_in = [r["key"] for r in inst.dashboard.get("reports", [])
               if metric in r.get("metrics", [])]
    derived = next(({"name": d["name"], "expr": d.get("expr"), "desc": d.get("desc")}
                    for d in inst.wide.get("wide", {}).get("derived", [])
                    if f"{d['name']}" in (m.get("expr") or "")), None)
    out = {"instance": inst_name, "metric": metric, "expr": m.get("expr"),
           "desc": m.get("desc"), "format": m.get("format"),
           "used_in_reports": used_in,
           "depends_on_derived": derived,
           "source": f"instances/{inst_name}/metrics.yml"}
    _audit("get_caliber", {"instance": inst_name, "metric": metric}, "1")
    return json.dumps(out, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import asyncio
        async def _selftest():
            for name, args in [("list_instances", {}), ("list_metrics", {"instance": "sales"}), ("list_reports", {"instance": "sales"}), ("query_report", {"instance": "sales", "report": "region_month", "filters": {"区域": "华东"}, "limit": 3}), ("get_data_status", {"instance": "sales"}), ("get_caliber", {"instance": "sales", "metric": "毛利率"})]:
                try:
                    res = await mcp.call_tool(name, args)
                    text = res[0][0].text if res and res[0] else ""
                    print(f"  ok  {name}: {text[:70]}".replace(chr(10), ' '))
                except Exception as e:
                    print(f"  FAIL {name}: {type(e).__name__}: {e}")
        asyncio.run(_selftest())
    else:
        mcp.run()
