# -*- coding: utf-8 -*-
"""跑批调度服务：定时器本体与参数管理（从 app/main.py 收纳而来，行为不变）。

默认完全手动触发——定时是可选功能，不是默认行为（决策 D5/D11）。
"""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.services import dbt_runner, settings as settings_svc

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _scheduled_build() -> None:
    inst = settings_svc.load().get("instance", "sales")
    dbt_runner.trigger_run(inst, "schedule")


def apply_schedule() -> dict:
    s = settings_svc.load()
    if s["schedule_enabled"]:
        scheduler.add_job(
            _scheduled_build, "cron",
            hour=s["schedule_hour"], minute=s["schedule_minute"],
            id="daily_build", replace_existing=True,
            misfire_grace_time=3600 * 6,
            coalesce=True,
        )
    else:
        try:
            scheduler.remove_job("daily_build")
        except Exception:
            pass
    return s


def schedule_info() -> dict:
    s = settings_svc.load()
    s["label"] = ("每天 {:02d}:{:02d}".format(s["schedule_hour"], s["schedule_minute"])
                  if s["schedule_enabled"] else "手动模式")
    s["next_run_time"] = None
    try:
        job = scheduler.get_job("daily_build")
        if job is not None and job.next_run_time is not None:
            s["next_run_time"] = job.next_run_time.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return s
