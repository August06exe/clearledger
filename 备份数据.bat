@echo off
chcp 65001 >nul
rem ============================================================
rem  ClearLedger backup - thin wrapper. All backup logic lives
rem  in ops\backup.py (one implementation shared by routine
rem  backups AND upgrade snapshots). Scope: data\warehouse\
rem  *.duckdb (+ .wal), data\runs, logs, per-instance six yml
rem  + onboarding\config_history, data\openapi_keys.json,
rem  data\settings.json, VERSION, requirements.txt. Writes
rem  backup_manifest.json (sha256/size/mtime per file) inside
rem  the backup folder. Layout mirrors repo-relative paths.
rem  Pass-through args: --tag <name> for upgrade-snapshot
rem  naming, --json for a machine-readable summary line.
rem  (Header comments kept ASCII on purpose: cmd's batch parser
rem   loses byte-sync on UTF-8 comment lines; Chinese lives only
rem   in echo lines, which are verified safe.)
rem ============================================================
cd /d %~dp0

if not exist ".venv\Scripts\python.exe" (
    echo [明账] 找不到 .venv\Scripts\python.exe——环境未初始化，先按 docs\AI-点火指南.md 自举
    pause
    exit /b 1
)

echo [明账] 备份开始（逻辑在 ops\backup.py，与升级快照同一实现）...
".venv\Scripts\python.exe" ops\backup.py %*
if errorlevel 1 (
    echo [明账] 备份有失败项！看上方 [失败] 行；逐文件指纹见备份目录内 backup_manifest.json
    pause
    exit /b 1
)

echo [明账] 备份完成。恢复方法：把备份目录内文件按相对路径整树复制回仓库根（金库回 data\warehouse\）。
pause
exit /b 0
