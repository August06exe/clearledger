# -*- coding: utf-8 -*-
"""跑批执行器：摄取（ingest）→ 转换（dbt build）→ 结果归档

- 跑批串行化：同一时刻只允许一个跑批（线程锁 + 状态标志）
- 每次跑批留痕：日志文件 + 归档 run_results + 运行历史 history.json
- 红绿灯判定：红 = 摄取失败或任一节点 error/fail；黄 = 任一测试 warn；绿 = 全部通过
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
from app.services import artifacts

_state_lock = threading.Lock()
_state = {"active": False, "run_id": None, "trigger": None}

HISTORY_FILE = config.RUNS_DIR / "history.json"
MAX_KEEP = 60


def status() -> dict:
    return dict(_state)


def history() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def latest_run() -> dict | None:
    h = history()
    return h[0] if h else None


def _save_history(runs: list[dict]) -> None:
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(runs[:MAX_KEEP], ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(HISTORY_FILE)


def _summarize(results_json: dict | None, ingest_ok: bool) -> tuple[dict, str]:
    """run_results.json → {uid: 节点结果} + 整体红绿灯"""
    idx = artifacts.node_index()
    nodes_out: dict[str, dict] = {}
    states: dict[str, str] = {}

    for r in (results_json or {}).get("results", []):
        uid = r["unique_id"]
        st = r.get("status") or "unknown"
        nodes_out[uid] = {
            "status": st,
            "time": round(r.get("execution_time") or 0, 2),
            "message": (r.get("message") or "").strip()[:600],
            "failures": r.get("failures"),
        }
        states[uid] = st

    # 结构里存在但本轮没执行的模型/测试（上游失败被跳过等）；源表从不被执行，不标记
    for uid in idx["nodes"]:
        if idx["nodes"][uid]["resource_type"] == "source":
            continue
        if uid not in nodes_out and results_json is not None:
            nodes_out[uid] = {"status": "not_run", "time": 0, "message": "本轮未执行（上游失败或未选中）", "failures": None}
            states[uid] = "not_run"

    if not ingest_ok:
        overall = "red"
    else:
        overall = artifacts.derive_status(states)
    return nodes_out, overall


def _pipeline(run_id: str, trigger: str) -> None:
    started = datetime.now().isoformat(timespec="seconds")
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = config.LOG_DIR / f"run_{run_id}.log"
    record: dict = {}

    def run_cmd(cmd: list[str], cwd: Path, log) -> int:
        log.write(f"\n$ {' '.join(str(c) for c in cmd)}   (cwd={cwd})\n")
        log.flush()
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([str(c) for c in cmd], cwd=str(cwd), stdout=log,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env)
        return p.returncode

    try:
        ingest_ok, ingest_report, dbt_rc = True, None, None
        results_json = None
        dbt_fail_reason = None
        start_epoch = time.time()
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"===== 跑批 {run_id}（触发：{trigger}）{started} =====\n")
            # 1) 摄取：inbox 文件 → raw 层
            ingest_rc = run_cmd([config.PYTHON, config.INGEST_PY], config.ROOT, log)
            ingest_ok = ingest_rc == 0
            try:
                ingest_report = json.loads((config.LOG_DIR / "ingest_last.json").read_text(encoding="utf-8"))
            except Exception:
                pass
            # 2) 转换：dbt build（摄取失败则跳过，直接红灯）
            if ingest_ok:
                dbt_rc = run_cmd([config.DBT_EXE, "build", "--profiles-dir", ".", "--no-use-colors"],
                                 config.DBT_DIR, log)
                if config.RUN_RESULTS.exists():
                    try:
                        # 只认本轮新生成的 run_results（防止 dbt 未写产物时拿上一轮旧结果"假绿"）
                        fresh = config.RUN_RESULTS.stat().st_mtime >= start_epoch - 2
                        candidate = json.loads(config.RUN_RESULTS.read_text(encoding="utf-8"))
                        if fresh:
                            results_json = candidate
                            config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
                            (config.RUNS_DIR / f"{run_id}_run_results.json").write_text(
                                json.dumps(results_json, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
            # 红绿灯总判定：红 = 摄取失败 或 dbt 失败 或 拿不到本轮运行结果
            if not ingest_ok:
                overall = "red"
                dbt_fail_reason = "摄取失败，已跳过 dbt 转换（下游被拦截）"
            elif dbt_rc not in (0, None) or results_json is None:
                overall = "red"
                dbt_fail_reason = f"dbt build 失败（返回码 {dbt_rc}）或未生成本轮运行结果，下游被拦截"
            else:
                nodes_out, overall = _summarize(results_json, True)

        if results_json is None:
            nodes_out = {}
        counts = {"total": len(nodes_out)}
        for n in nodes_out.values():
            counts[n["status"]] = counts.get(n["status"], 0) + 1
        record = {
            "run_id": run_id,
            "trigger": trigger,
            "started_at": started,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": overall,
            "ingest_ok": ingest_ok,
            "ingest": ingest_report,
            "dbt_returncode": dbt_rc,
            "counts": counts,
            "nodes": nodes_out,
            "log_file": str(log_path),
        }
        if dbt_fail_reason:
            record["error"] = dbt_fail_reason
    except Exception as e:  # 兜底：执行器自身异常也必须留痕并亮红灯
        record = {
            "run_id": run_id, "trigger": trigger, "started_at": started,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "red", "ingest_ok": False, "ingest": None,
            "dbt_returncode": None, "counts": {}, "nodes": {},
            "log_file": str(log_path), "error": str(e),
        }
    finally:
        _save_history([record] + history())
        # 清理已滚出保留期的 run_results 归档
        try:
            kept = {r["run_id"] for r in history()}
            for f in config.RUNS_DIR.glob("*_run_results.json"):
                if f.name.replace("_run_results.json", "") not in kept:
                    f.unlink(missing_ok=True)
        except Exception:
            pass
        with _state_lock:
            _state.update(active=False, run_id=None)


def trigger_run(trigger: str = "manual") -> str | None:
    """启动一次跑批；若已有跑批在进行则返回 None（API 层转 409）"""
    with _state_lock:
        if _state["active"]:
            return None
        run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        _state.update(active=True, run_id=run_id, trigger=trigger)
    threading.Thread(target=_pipeline, args=(run_id, trigger), daemon=True).start()
    return run_id
