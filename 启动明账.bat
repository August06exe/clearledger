@echo off
rem ============================================================
rem  明账 ClearLedger — 一键启动
rem  双击后自动准备环境、启动门户，并打开浏览器
rem  地址：http://127.0.0.1:8620
rem ============================================================
chcp 65001 >nul
cd /d %~dp0
title 明账 ClearLedger

if not exist .venv (
    echo [明账] 首次运行，正在创建运行环境（约 2~5 分钟，只需一次）...
    python -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip -q
    .venv\Scripts\python -m pip install -r requirements.txt -q
)

echo [明账] 正在启动门户服务...
set PYTHONUTF8=1
start "" /b cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8620"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8620

echo.
echo [明账] 服务已停止。窗口可以关闭。
pause
