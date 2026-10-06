# -*- coding: utf-8 -*-
"""路由公共助手：异常翻译、当前账套、过期信息（原 app/main.py 私有函数，行为不变）。"""
from __future__ import annotations

import duckdb
from fastapi import HTTPException

from semantic.loader import ConfigError

from app.services import dbt_runner, settings as settings_svc


def guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        # 客户端参数非法（如筛选维度名不存在）→ 4xx，不得伪装"服务端不可用"
        raise HTTPException(400, f"请求参数非法：{e}")
    except (FileNotFoundError, RuntimeError, ConfigError, duckdb.Error) as e:
        raise HTTPException(503, f"数据暂不可用（可能正在跑批或尚未初始化）：{e}")


def current_instance() -> str:
    return settings_svc.load().get("instance", "sales")


def stale_info() -> tuple[bool, str | None]:
    inst = current_instance()
    run = dbt_runner.latest_run(inst)
    if run and run.get("status") == "red":
        return True, f"账套[{inst}] 最近一次跑批失败（{run.get('finished_at', '')}），以下为最近一次成功跑批的旧数据"
    return False, None
