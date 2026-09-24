# -*- coding: utf-8 -*-
"""配置工作台（v0.5）：六块配置的读取 / 草稿校验 / 保存 / 挂起队列 / 影响预览

设计契约见 docs/设计-v0.5-配置工作台.md。要点：
- 块白名单封闭，实例名防穿越，保存原子写 + 固定路径滚动备份；
- 草稿校验 = 草稿替换该块 + 其余块取磁盘现状 → 引擎加载器全套交叉校验（临时目录，绝不落盘）；
- 挂起队列 = raw.contract_report 最近 run 的稳定投影（跨双跑逐字节可比）；
- 影响预览纯配置推导（GUI 与 agent 同源双入口，无新口径）。
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from semantic.loader import CONFIG_FILES, ConfigError, Instance, load_instance, load_instance_dir

BLOCK_FILES: dict[str, str] = {
    "instance": "instance.yml",
    **CONFIG_FILES,  # sources / wide / dimensions / metrics / dashboard
}

_BACKUP_RELPATH = Path("onboarding") / "config_history"

_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")  # 允许 _ 前缀（测试副本约定），禁 . / \ 等


class WorkbenchError(Exception):
    """工作台操作错误（实例/块不可寻址等）——映射 404"""


def instance_dir(instance: str) -> Path:
    """实例目录解析：名称合法性 + 目录存在 + 必须落在允许的根之下（防穿越）。

    允许根：instances/（正式账套）与 tests/fixtures/instances/（测试夹具账套）。
    """
    if not isinstance(instance, str) or not _NAME_RE.match(instance or ""):
        raise WorkbenchError(f"实例名不合法: {instance!r}")
    roots = [
        Path(__file__).resolve().parents[2] / "instances",
        Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "instances",
    ]
    for r in roots:
        d = (r / instance).resolve()
        if r.resolve() in d.parents and d.is_dir():
            return d
    raise WorkbenchError(f"实例不存在: {instance}")


def block_file(block: str) -> str:
    if block not in BLOCK_FILES:
        raise WorkbenchError(f"未知配置块: {block}")
    return BLOCK_FILES[block]


# ---------------------------------------------------------------- 概览 / 读取
def overview(instance: str) -> dict:
    d = instance_dir(instance)
    meta = {}
    try:
        meta = yaml.safe_load((d / "instance.yml").read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    blocks = []
    for block, fname in BLOCK_FILES.items():
        p = d / fname
        blocks.append({
            "block": block, "file": fname, "exists": p.exists(),
            "size": p.stat().st_size if p.exists() else 0,
            "mtime": _mtime_iso(p),
        })
    return {"instance": instance, "title": (meta or {}).get("title", instance), "blocks": blocks}


def read_block(instance: str, block: str) -> dict:
    d = instance_dir(instance)
    fname = block_file(block)
    p = d / fname
    if not p.exists():
        raise WorkbenchError(f"配置文件不存在: {instance}/{fname}")
    content = p.read_text(encoding="utf-8")
    parse_error = None
    try:
        yaml.safe_load(content)
    except Exception as e:
        parse_error = str(e).splitlines()[0]
    return {"instance": instance, "block": block, "file": fname,
            "content": content, "parsed_ok": parse_error is None, "parse_error": parse_error}


# ---------------------------------------------------------------- 草稿校验
def validate_draft(instance: str, block: str, content: str) -> dict:
    """三层校验：YAML 语法 → 映射 → 引擎交叉校验（临时目录组装，零落盘）。"""
    d = instance_dir(instance)
    block_file(block)  # 白名单检查
    errors: list[str] = []
    try:
        data = yaml.safe_load(content)
    except Exception as e:
        return {"ok": False, "errors": [f"YAML 解析失败: {str(e).splitlines()[0]}"], "warnings": []}
    if not isinstance(data, dict):
        return {"ok": False, "errors": ["配置文件格式错误（应为映射）"], "warnings": []}

    with tempfile.TemporaryDirectory(prefix="wb_validate_") as tmp:
        tmpd = Path(tmp)
        for fname in BLOCK_FILES.values():
            src = d / fname
            if src.exists():
                shutil.copyfile(src, tmpd / fname)
        (tmpd / BLOCK_FILES[block]).write_text(content, encoding="utf-8")
        try:
            load_instance_dir(tmpd, instance)
        except ConfigError as e:
            errors = [line for line in str(e).splitlines() if line.strip()]
    return {"ok": not errors, "errors": errors, "warnings": []}


# ---------------------------------------------------------------- 保存
def save_block(instance: str, block: str, content: str, rebuild: bool,
               trigger_run) -> dict:
    """校验 → 备份 → 原子写 → 可选重建。trigger_run 由调用方注入（dbt_runner.trigger_run）。"""
    d = instance_dir(instance)
    fname = block_file(block)
    check = validate_draft(instance, block, content)
    if not check["ok"]:
        return {"ok": False, "errors": check["errors"], "http": 422}

    target = d / fname
    backup_dir = d / _BACKUP_RELPATH
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{block}.prev.yml"
    if target.exists():
        shutil.copyfile(target, backup)

    tmp = target.with_suffix(".yml.tmp")
    tmp.write_text(content, encoding="utf-8", newline="")  # 保留原换行符，杜绝 LF→CRLF 字节抖动
    os.replace(tmp, target)

    affected = affected_reports(instance, block, content)
    rb: dict = {"triggered": False, "run_id": None, "reason": None}
    if rebuild:
        run_id = trigger_run(instance, "workbench")
        if run_id is None:
            rb["reason"] = "run_in_progress"
        else:
            rb.update(triggered=True, run_id=run_id)
    return {"ok": True, "block": block, "backup": str(backup.relative_to(d.parent.parent)),
            "affected_reports": affected, "rebuild": rb, "http": 200}


# ---------------------------------------------------------------- 影响预览
def impact_map(instance: str) -> dict:
    inst = _load_live(instance)
    reports = inst.dashboard.get("reports", [])
    metrics = {m["name"]: sorted(r["key"] for r in reports
                                 if m["name"] in (r.get("metrics") or []))
               for m in inst.metrics}
    dims: dict[str, set[str]] = {d["name"]: set() for d in inst.dimensions}
    for r in reports:
        used = {r["dimension"], *(r.get("filters") or [])}
        if r.get("time_dim"):
            used.add(r["time_dim"])
        for name in used:
            if name in dims:
                dims[name].add(r["key"])
    dimensions = {k: sorted(v) for k, v in dims.items()}
    return {"instance": instance,
            "metrics": dict(sorted(metrics.items())),
            "dimensions": dict(sorted(dimensions.items()))}


def affected_reports(instance: str, block: str, draft_content: str) -> list[str]:
    """保存响应里的影响面（保守口径，见设计文档 §3.4）：
    metrics=草稿中出现的任一指标名被引用的报表并集；dashboard=草稿全部报表 key；其余 []。"""
    if block not in ("metrics", "dashboard"):
        return []
    try:
        data = yaml.safe_load(draft_content)
    except Exception:
        return []
    try:
        live = impact_map(instance)
    except ConfigError:
        live = {"metrics": {}, "dimensions": {}}
    if block == "metrics":
        names = {m.get("name") for m in (data.get("metrics") or []) if isinstance(m, dict)}
        return sorted({r for n in names for r in live["metrics"].get(n, [])})
    return sorted(r.get("key") for r in (data.get("reports") or []) if r.get("key"))


# ---------------------------------------------------------------- 挂起队列
def pending_items(instance: str) -> dict:
    from semantic.query import _connect
    try:
        inst: Instance = load_instance(instance)
    except ConfigError as e:
        raise WorkbenchError(str(e))
    db = (inst.pipeline_dir / inst.db_path).resolve()
    if not db.exists():
        return {"instance": instance, "latest_run": None, "items": [], "note": "no_db"}
    con = _connect(inst, readonly=True)
    try:
        rows = con.execute("""
            select run_id, source, field, rule, level, cnt, sample
            from raw.contract_report
            where run_id = (select max(run_id) from raw.contract_report)
            order by source, field, rule
        """).fetchall()
    except Exception:
        return {"instance": instance, "latest_run": None, "items": [], "note": "no_table"}
    finally:
        con.close()
    items = [{"source": r[1], "field": r[2], "rule": r[3], "level": r[4],
              "cnt": int(r[5] or 0), "sample": (r[6] or "")}
             for r in rows]
    latest_run = None
    if rows:
        # 链内跑批把 dbt run_id 传给了 ingest（--run-id），契约行与跑批历史同 ID 精确对齐；
        # CLI 直跑的摄取没有历史记录，light/finished_at 诚实留空
        ingest_run_id = rows[0][0]
        light = finished = None
        try:
            from app.services import dbt_runner
            rec = next((r for r in dbt_runner.all_history()
                        if r.get("run_id") == ingest_run_id), None)
            if rec:
                st = rec.get("status")
                light = {"success": "green", "warn": "yellow"}.get(st, st)
                finished = rec.get("finished_at")
        except Exception:
            pass
        latest_run = {"run_id": ingest_run_id, "finished_at": finished, "light": light}
    return {"instance": instance, "latest_run": latest_run, "items": items, "note": None}


# ---------------------------------------------------------------- 内部
def _load_live(instance: str) -> Instance:
    d = instance_dir(instance)
    try:
        return load_instance_dir(d, instance)
    except ConfigError as e:
        raise WorkbenchError(str(e))


def _mtime_iso(p: Path) -> str | None:
    if not p.exists():
        return None
    from datetime import datetime
    return datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
