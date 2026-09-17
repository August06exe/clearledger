@echo off
rem ============================================================
rem  明账 ClearLedger — 一键备份
rem  把数据仓库、跑批历史、日志打包到 data\backup\日期 文件夹
rem ============================================================
chcp 65001 >nul
cd /d %~dp0

set STAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%
set STAMP=%STAMP: =0%
set DEST=data\backup\%STAMP%

echo [明账] 备份到 %DEST% ...
mkdir "%DEST%" 2>nul
copy /y "data\warehouse\warehouse.duckdb" "%DEST%\" >nul
xcopy /y /s /q "data\runs" "%DEST%\runs\" >nul
xcopy /y /s /q "logs" "%DEST%\logs\" >nul

echo [明账] 备份完成：data\backup\%STAMP%
echo         提示：备份 = 复制这一个 warehouse.duckdb 文件，恢复 = 把它复制回来。
pause
