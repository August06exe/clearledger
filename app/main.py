# -*- coding: utf-8 -*-
"""明账 ClearLedger — 门户后端装配入口（v0.3 实例化版；路由收纳于 app/routers/ 六模块）

账套模型：settings.instance 指向当前公司账套，全部数据 API 按账套路由到
instances/<n>/（五配置）与 data/warehouse/<n>.duckdb（独立库）。旧手写管道已退役。
启动：.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8620
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import config
from app.services import dbt_runner, settings as settings_svc
from app.services.schedule import scheduler, apply_schedule
from app.routers import portal, lineage, reports, runs, workbench, open_api


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    apply_schedule()
    # 定时模式下的启动补跑（>24h 断档）；手动模式绝不自动跑（决策 D5/D11）
    try:
        s = settings_svc.load()
        runs_hist = dbt_runner.history(s["instance"])
        stale = not runs_hist or datetime.fromisoformat(runs_hist[0]["finished_at"]) < datetime.now() - timedelta(hours=24)
        if s["schedule_enabled"] and stale and not dbt_runner.status()["active"]:
            dbt_runner.trigger_run(s["instance"], "catchup")
    except Exception:
        pass
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def no_cache_html(request, call_next):
    """根治缓存事故：入口 html 禁缓存（否则升级后浏览器拿旧 index.html 引旧 JS，
    与新 API 字段错位导致页面空白——真实踩坑）；带版本号的 js/css 仍可长缓存"""
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if "text/html" in ct:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


app.include_router(portal.router)
app.include_router(lineage.router)
app.include_router(reports.router)
app.include_router(runs.router)
app.include_router(workbench.router)
app.include_router(open_api.router)

# 前端静态页（必须最后挂载：/ 兜底）
app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
