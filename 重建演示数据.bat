@echo off
rem ============================================================
rem  明账 ClearLedger — 重建演示数据
rem  重新生成仿真数据 → 摄取 → 跑批，恢复到开箱演示状态
rem  （会覆盖 data\warehouse\warehouse.duckdb 中的当前数据）
rem ============================================================
chcp 65001 >nul
cd /d %~dp0

echo [明账] 生成演示数据...
.venv\Scripts\python.exe sample_data\generate.py || goto :err
echo [明账] 摄取入库...
.venv\Scripts\python.exe ingest\ingest.py || goto :err
echo [明账] 跑批（dbt build）...
cd pipeline
..\.venv\Scripts\dbt.exe build --profiles-dir . --no-use-colors || goto :err
cd ..
echo [明账] 演示数据已重建，刷新浏览器即可。
pause
exit /b 0
:err
echo [明账] 出错了，请截图保存输出，发给 AI 助手排查。
pause
exit /b 1
