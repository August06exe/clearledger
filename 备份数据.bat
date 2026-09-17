@echo off
rem ============================================================
rem  明账 ClearLedger — 一键备份
rem  把数据仓库、跑批历史、日志备份到 data\backup\日期 文件夹
rem  注意：跑批进行中请勿备份（先看门户是否显示"跑批中"）
rem ============================================================
chcp 65001 >nul
cd /d %~dp0

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set STAMP=%%i
set DEST=data\backup\%STAMP%

if not exist "data\warehouse\warehouse.duckdb" (
    echo [明账] 备份失败：找不到 data\warehouse\warehouse.duckdb
    pause
    exit /b 1
)

echo [明账] 备份到 %DEST% ...
mkdir "%DEST%" 2>nul
copy /y "data\warehouse\warehouse.duckdb" "%DEST%\" >nul || goto :err
if exist "data\warehouse\warehouse.duckdb.wal" copy /y "data\warehouse\warehouse.duckdb.wal" "%DEST%\" >nul || goto :err
xcopy /y /s /q "data\runs" "%DEST%\runs\" >nul || goto :err
xcopy /y /s /q "logs" "%DEST%\logs\" >nul || goto :err

echo [明账] 备份完成：data\backup\%STAMP%
echo         恢复方法：把 warehouse.duckdb 复制回 data\warehouse\ 即可。
pause
exit /b 0

:err
echo [明账] 备份失败！可能是文件被占用（门户正在跑批/查询），请稍后再试。
pause
exit /b 1
