@echo off
chcp 65001 >nul
rem ============================================================
rem  ClearLedger one-click backup (multi-instance edition)
rem  Backs up every instance warehouse (data\warehouse\*.duckdb),
rem  run history (data\runs) and logs into data\backup\<timestamp>
rem  NOTE: do not run while a pipeline job is in progress.
rem  (Header comments kept ASCII on purpose: cmd's batch parser
rem   loses byte-sync on UTF-8 comment lines; Chinese lives only
rem   in echo lines, which are verified safe.)
rem ============================================================
cd /d %~dp0

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set STAMP=%%i
set DEST=data\backup\%STAMP%
set FAILED=0

if not exist "data\warehouse\*.duckdb" (
    echo [明账] 备份失败：data\warehouse\ 下找不到任何账套金库（*.duckdb）
    pause
    exit /b 1
)

echo [明账] 备份到 %DEST% ...
mkdir "%DEST%" 2>nul
for %%f in ("data\warehouse\*.duckdb") do (
    copy /y "%%~ff" "%DEST%\" >nul
    if errorlevel 1 (set FAILED=1) else echo   [OK] %%~nxf
    if exist "%%~ff.wal" copy /y "%%~ff.wal" "%DEST%\" >nul
)
xcopy /y /s /q "data\runs" "%DEST%\runs\" >nul || set FAILED=1
xcopy /y /s /q "logs" "%DEST%\logs\" >nul || set FAILED=1

if "%FAILED%"=="1" (
    echo [明账] 备份有失败项！可能是文件被占用（门户正在跑批/查询），请稍后再试。
    pause
    exit /b 1
)

echo [明账] 备份完成：data\backup\%STAMP%
echo         恢复方法：把对应账套的 .duckdb 复制回 data\warehouse\ 即可。
pause
exit /b 0
