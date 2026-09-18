@echo off
rem ============================================================
rem  明账 ClearLedger — 重建演示数据（双账套）
rem  销售公司 + 连锁餐饮：生成 → 语义摄取 → 编译 → dbt build
rem  （覆盖各自 data\warehouse\<账套>.duckdb，恢复开箱演示状态）
rem ============================================================
chcp 65001 >nul
cd /d %~dp0

echo [明账] 生成演示数据（销售公司 + 连锁餐饮）...
.venv\Scripts\python.exe sample_data\generate.py || goto :err
.venv\Scripts\python.exe sample_data\generate_restaurant.py || goto :err

for %%i in (sales restaurant) do (
    echo [明账] 账套 %%i：语义摄取...
    .venv\Scripts\python.exe -m semantic.ingest_run --instance %%i || goto :err
    echo [明账] 账套 %%i：编译配置...
    .venv\Scripts\python.exe -m semantic.compile_dbt --instance %%i || goto :err
    echo [明账] 账套 %%i：跑批...
    pushd instances\%%i\pipeline
    ..\..\..\.venv\Scripts\dbt.exe build --profiles-dir . --no-use-colors || goto :err
    popd
)

echo [明账] 双账套演示数据已重建，刷新浏览器即可（顶栏可切换账套）。
pause
exit /b 0
:err
echo [明账] 出错了，请截图保存输出，发给 AI 助手排查。
pause
exit /b 1
