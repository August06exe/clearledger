# -*- coding: utf-8 -*-
"""跑批路由：历史、状态、触发、详情、Gantt、日志（原 app/main.py，行为不变）。

路由顺序敏感：/api/runs/status 必须注册在 /api/runs/{run_id} 之前。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from semantic.loader import load_instance

from app import config
from app.services import dbt_runner
from app.routers.deps import current_instance

router = APIRouter()


@router.get("/api/runs")
def api_runs(instance: str | None = None):
    runs = dbt_runner.history(instance) if instance else dbt_runner.all_history()
    return {"runs": [
        {k: r.get(k) for k in ("run_id", "instance", "trigger", "started_at",
                               "finished_at", "status", "counts")}
        for r in runs
    ]}


@router.get("/api/runs/status")
def api_run_status():
    return dbt_runner.status()


@router.post("/api/runs/trigger")
def api_run_trigger(instance: str | None = None):
    inst = instance or current_instance()
    run_id = dbt_runner.trigger_run(inst, "manual")
    if run_id is None:
        raise HTTPException(409, "已有跑批在进行中")
    return {"run_id": run_id, "instance": inst, "message": f"账套[{inst}] 跑批已启动"}


@router.get("/api/runs/{run_id}")
def api_run_detail(run_id: str):
    run = next((r for r in dbt_runner.all_history() if r["run_id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "运行记录不存在")
    manifest_uids: dict[str, dict] = {}
    try:
        inst = load_instance(run.get("instance") or current_instance())
        mp = inst.pipeline_dir / "target" / "manifest.json"
        if mp.exists():
            mm = json.loads(mp.read_text(encoding="utf-8"))
            manifest_uids = {uid: n.get("name", uid) for uid, n in mm.get("nodes", {}).items()}
    except Exception:
        pass

    def _row(uid: str, n: dict):
        return {"uid": uid, "name": manifest_uids.get(uid, uid.split(".")[-1] if uid else uid),
                "kind": "model" if uid.startswith("model.") else ("test" if uid.startswith("test.") else "?"),
                "status": n.get("status"), "time": n.get("time"), "message": n.get("message")}

    nodes = [_row(uid, n) for uid, n in run.get("nodes", {}).items()]
    nodes.sort(key=lambda r: (0 if r["kind"] == "model" else 1, r["name"]))
    return {**{k: run.get(k) for k in ("run_id", "instance", "trigger", "started_at", "finished_at",
                                       "status", "ingest_ok", "ingest", "counts", "error", "dbt_returncode")},
            "nodes": nodes}


@router.get("/api/runs/{run_id}/gantt")
def api_run_gantt(run_id: str):
    """瀑布图数据：逐节点取 dbt run_results 里 Execute 段的起止时刻。

    数据源优先 data/runs/<run_id>_run_results.json（跑批归档，含本轮 timing），
    缺失时回退 instances/<账套>/pipeline/target/run_results.json（仅当该 run
    恰是账套最近一轮时才对得上）。offset = 该节点起点 − 全轮最早起点。
    """
    run = next((r for r in dbt_runner.all_history() if r["run_id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "运行记录不存在")

    rr = config.RUNS_DIR / f"{run_id}_run_results.json"
    if not rr.exists():
        try:
            inst = load_instance(run.get("instance") or current_instance())
            rr = inst.pipeline_dir / "target" / "run_results.json"
        except Exception:
            pass
    if not rr.exists():
        raise HTTPException(404, "未找到该轮 run_results（可能已被清理）")
    try:
        data = json.loads(rr.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(404, "run_results 解析失败")

    results = data.get("results") or []
    if not results:
        raise HTTPException(404, "run_results 无节点结果")

    def _seg(r: dict):
        """取 timing 里的 Execute 段（无则退最后一段）→ 时区对齐的 (started, completed)"""
        timing = r.get("timing") or []
        seg = next((t for t in timing if str(t.get("name") or "").lower() == "execute"),
                   timing[-1] if timing else None)
        if not seg or not seg.get("started_at") or not seg.get("completed_at"):
            return None
        try:
            def _dt(v: str) -> datetime:
                d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            return _dt(seg["started_at"]), _dt(seg["completed_at"])
        except Exception:
            return None

    parsed = [(r, seg) for r in results if (seg := _seg(r)) is not None]
    if not parsed:
        raise HTTPException(404, "run_results 无可用的节点起止时刻")

    t0 = min(s for _, (s, _e) in parsed)
    t1 = max(e for _, (_s, e) in parsed)
    nodes = [{
        "name": (r.get("unique_id") or "").split(".")[-1],
        "status": r.get("status"),
        "offset_s": round((s - t0).total_seconds(), 3),
        "duration_s": round(max((e - s).total_seconds(), 0.0), 3),
        "message": (r.get("message") or "").strip()[:200],
    } for r, (s, e) in parsed]
    nodes.sort(key=lambda n: (n["offset_s"], n["name"]))
    return {
        "run_id": run_id,
        "instance": run.get("instance"),
        "status": run.get("status"),
        "trigger": run.get("trigger"),
        "total_s": round(max((t1 - t0).total_seconds(), 0.0), 3),
        "nodes": nodes,
    }


@router.get("/api/runs/{run_id}/log")
def api_run_log(run_id: str, tail: int = 300):
    run = next((r for r in dbt_runner.all_history() if r["run_id"] == run_id), None)
    if run is None:
        raise HTTPException(404, "运行记录不存在")
    log_file = Path(run.get("log_file", ""))
    if not log_file.exists():
        return PlainTextResponse("(无日志)")
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    return PlainTextResponse("\n".join(lines[-max(10, min(tail, 2000)):]))
