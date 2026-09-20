# -*- coding: utf-8 -*-
"""跑批执行器（v0.3 实例链路版）：语义摄取 → 编译 → dbt build → 结果归档

- 账套感知：按 settings.instance 跑对应实例；运行历史按账套分文件
- 跑批串行化：同一时刻全系统只允许一个跑批（跨账套互斥，DuckDB 单写者×多实例）
- 红绿灯：红 = 任一环节退出码非零或无本轮产物；黄 = dbt 测试 warn；绿 = 全部通过
- 旧手写管道已退役（v0.3）：pipeline/ 与 ingest/ingest.py 旧入口已删除，git 可回滚
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from app import config
from app.services import settings as settings_svc

_state_lock = threading.Lock()
_state = {"active": False, "run_id": None, "trigger": None, "instance": None}

FAIL_STATES = {"error", "fail", "runtime error"}


def derive_status(node_status: dict[str, str]) -> str:
    """由各节点状态推导整体红绿灯：red > yellow > green"""
    states = set(node_status.values())
    if states & FAIL_STATES:
        return "red"
    if "warn" in states:
        return "yellow"
    return "green"


def status() -> dict:
    return dict(_state)


def _history_file(instance: str) -> Path:
    return config.RUNS_DIR / f"history_{instance}.json"


def history(instance: str) -> list[dict]:
    f = _history_file(instance)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def latest_run(instance: str) -> dict | None:
    h = history(instance)
    return h[0] if h else None


def all_history() -> list[dict]:
    """跨账套合并视图（跑批历史页/概览用），按开始时间倒序"""
    merged = []
    if config.RUNS_DIR.exists():
        for f in config.RUNS_DIR.glob("history_*.json"):
            try:
                merged.extend(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
    return sorted(merged, key=lambda r: r.get("started_at", ""), reverse=True)


def _save_history(instance: str, runs: list[dict]) -> None:
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    f = _history_file(instance)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(runs[:60], ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def _summarize_dbt(run_results: dict | None, idx_nodes: dict[str, dict]) -> tuple[dict, dict, str]:
    """run_results → {uid: 节点结果} + 状态字典"""
    nodes_out: dict[str, dict] = {}
    states: dict[str, str] = {}
    for r in (run_results or {}).get("results", []):
        uid = r["unique_id"]
        st = r.get("status") or "unknown"
        nodes_out[uid] = {
            "status": st,
            "time": round(r.get("execution_time") or 0, 2),
            "message": (r.get("message") or "").strip()[:600],
            "failures": r.get("failures"),
        }
        states[uid] = st
    return nodes_out, states


def _pipeline(instance: str, run_id: str, trigger: str) -> None:
    from semantic.loader import load_instance

    started_dt = datetime.now()
    started = started_dt.isoformat(timespec="seconds")
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = config.LOG_DIR / f"run_{instance}_{run_id}.log"
    record: dict = {}
    nodes_out: dict = {}

    def run_cmd(cmd: list[str], cwd: Path, log) -> int:
        log.write(f"\n$ {' '.join(str(c) for c in cmd)}   (cwd={cwd})\n")
        log.flush()
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([str(c) for c in cmd], cwd=str(cwd), stdout=log,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env)
        return p.returncode

    try:
        inst = load_instance(instance)
        ingest_rc = compile_rc = dbt_rc = None
        ingest_report = None
        results_json = None
        fail_reason = None
        start_epoch = time.time()

        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"===== 账套[{instance}] 跑批 {run_id}（触发：{trigger}）{started} =====\n")
            # 1) 语义摄取（入口档案+字段契约）
            ingest_rc = run_cmd([config.PYTHON, "-m", "semantic.ingest_run", "--instance", instance,
                                 "--run-id", run_id],
                                config.ROOT, log)
            ingest_ok = ingest_rc == 0
            try:
                ingest_report = json.loads(
                    (config.LOG_DIR / f"ingest_{instance}_last.json").read_text(encoding="utf-8"))
            except Exception:
                pass
            if not ingest_ok:
                fail_reason = f"摄取失败（返回码 {ingest_rc}），已停止后续环节"
            else:
                # 2) 编译五配置 → dbt project
                compile_rc = run_cmd([config.PYTHON, "-m", "semantic.compile_dbt",
                                      "--instance", instance], config.ROOT, log)
                if compile_rc != 0:
                    fail_reason = f"配置编译失败（返回码 {compile_rc}）"
                else:
                    # 3) dbt build
                    dbt_rc = run_cmd([config.DBT_EXE, "build", "--profiles-dir", ".", "--no-use-colors"],
                                     inst.pipeline_dir, log)
                    rr_path = inst.pipeline_dir / "target" / "run_results.json"
                    if rr_path.exists():
                        try:
                            fresh = rr_path.stat().st_mtime >= start_epoch - 2
                            candidate = json.loads(rr_path.read_text(encoding="utf-8"))
                            if fresh:
                                results_json = candidate
                                config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
                                (config.RUNS_DIR / f"{run_id}_run_results.json").write_text(
                                    json.dumps(results_json, ensure_ascii=False), encoding="utf-8")
                        except Exception:
                            pass

        # 红绿灯总判定（红灯语义：任一环节退出码非零，或 dbt 无本轮新鲜产物）
        overall = "green"
        if ingest_rc not in (0, None):
            overall = "red"
            fail_reason = fail_reason or f"摄取失败（返回码 {ingest_rc}）"
        elif compile_rc not in (0, None):
            overall = "red"
            fail_reason = fail_reason or f"编译失败（返回码 {compile_rc}）"
        elif dbt_rc not in (0, None) or results_json is None:
            overall = "red"
            fail_reason = fail_reason or f"dbt build 失败（返回码 {dbt_rc}）或未生成本轮运行结果"
        if results_json is not None:
            nodes_out, states = _summarize_dbt(results_json, {})
            if not fail_reason:
                overall = derive_status(states)

        counts = {"total": len(nodes_out)}
        for n in nodes_out.values():
            counts[n["status"]] = counts.get(n["status"], 0) + 1
        record = {
            "run_id": run_id, "instance": instance, "trigger": trigger,
            "started_at": started,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": overall,
            "ingest": ingest_report,
            "ingest_ok": ingest_rc in (0, None),
            "compile_returncode": compile_rc,
            "dbt_returncode": dbt_rc,
            "counts": counts,
            "nodes": nodes_out,
            "log_file": str(log_path),
        }
        if fail_reason:
            record["error"] = fail_reason
    except Exception as e:
        record = {
            "run_id": run_id, "instance": instance, "trigger": trigger,
            "started_at": started,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "red", "counts": {}, "nodes": {},
            "log_file": str(log_path), "error": f"{type(e).__name__}: {e}",
        }
    finally:
        _save_history(instance, [record] + history(instance))
        try:
            kept = {r["run_id"] for r in history(instance)}
            for f in config.RUNS_DIR.glob("*_run_results.json"):
                if f.name.replace("_run_results.json", "") not in kept:
                    f.unlink(missing_ok=True)
        except Exception:
            pass
        with _state_lock:
            _state.update(active=False, run_id=None, instance=None)


def trigger_run(instance: str, trigger: str = "manual") -> str | None:
    """启动指定账套的跑批；全系统互斥（有跑批在跑返回 None）"""
    with _state_lock:
        if _state["active"]:
            return None
        run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        _state.update(active=True, run_id=run_id, trigger=trigger, instance=instance)
    threading.Thread(target=_pipeline, args=(instance, run_id, trigger), daemon=True).start()
    return run_id
