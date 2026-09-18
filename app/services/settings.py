# -*- coding: utf-8 -*-
"""门户设置（持久化到 data/settings.json）

设计原则：定时跑批是"可开关的功能"，默认完全手动触发；
开关与时间在门户界面即可调整，无需改代码、重启后保持。
"""
from __future__ import annotations

import json

from app import config

FILE = config.DATA_DIR / "settings.json"
DEFAULTS = {
    "schedule_enabled": config.SCHEDULE_ENABLED_DEFAULT,
    "schedule_hour": config.SCHEDULE_HOUR,
    "schedule_minute": config.SCHEDULE_MINUTE,
}


def load() -> dict:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    merged = {**DEFAULTS, **{k: data.get(k, v) for k, v in DEFAULTS.items()}}
    merged["schedule_enabled"] = bool(merged["schedule_enabled"])
    merged["schedule_hour"] = max(0, min(23, int(merged["schedule_hour"])))
    merged["schedule_minute"] = max(0, min(59, int(merged["schedule_minute"])))
    return merged


def save(patch: dict) -> dict:
    merged = {**load(), **patch}
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(FILE)
    return merged
