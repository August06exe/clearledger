# AGENTS.md — AI 代理接管入口

> 你（AI agent）被派来维护/扩展这个项目时，**从本文件开始**。
> 本项目第一性原则：**AI-Native**——系统的第一读者和第一操作者都是 AI，
> 人类只做验收与拍板。因此本文档的存在本身就是产品需求，不是附赠品。

## 30 秒认知

- 项目：**明账 ClearLedger**——私有化管理报表数据底座（DuckDB + dbt + FastAPI + 原生 JS 门户）
- 平台：Windows 本机，Git Bash，Python venv 在 `.venv/`（Windows 路径 `.venv\Scripts\`）
- 门户：`http://127.0.0.1:8620`（仅本机监听，无认证——有意为之，见决策 D4）
- 数据流：`data/inbox/`(Excel/CSV) → `ingest/ingest.py`(清洗入库 raw) → `pipeline/`(dbt 三层) → `app/`(门户)
- 当前状态：main=develop（验收已合并）；业务层写死收入/毛利口径与 5 张报表，
  **v0.5 计划将其改造为五份配置文件的"通用积木"**（见 docs/语义层设计 待写）

## 必读文件（按顺序）

1. **docs/AI-操作手册.md** — 系统地图、状态资产清单、操作配方、故障 playbook、你的自动化 SOP
2. docs/指标口径.md — 业务口径唯一定义（改数字相关的代码前必读）
3. docs/待确认与决策.md — 所有已拍板决策与红线（D1~D13），不要推翻已有决策
4. docs/迭代日志.md — 历史教训库（前人踩过的坑，按时间组织；手册里按症状重新组织过）

## 红线（违反 = 事故）

- **口径唯一出处**：指标计算只允许存在于 dbt 模型/未来 metrics 配置中，报表层与前端只引用不重算
- **报表只读 marts 层**：`app/services/reports.py` 的 SQL 不许碰 staging/raw
- **改任何 pipeline/ 下 SQL 后必须跑一次 `dbt build`** 确认 55 节点无 error（当前基线：12 模型 + 43 测试，1 warn 是预埋演示异常，属预期）
- **改前端静态文件必须升版本号**：`app/static/index.html` 里的 `?v=YYYYMMDDx` 串，否则浏览器用旧缓存——这是真实踩过的坑
- **Git Bash 里禁止 `>nul` 重定向**（会创建名为 nul 的真实文件导致 git add 崩溃，已两次踩坑）；静默输出用 `>/dev/null`
- **跑批期间仓库带写锁**：直接查 DuckDB 用 `app/services/duck.py` 的重试连接，不要裸 connect
- data/ 与 logs/ 不入 git（.gitignore 有意为之）；`data/warehouse/warehouse.duckdb` 是全部业务数据，动它之前先跑 备份数据.bat

## 快速命令

```bash
# 自检（你应该在动手前先跑这个）
.venv/Scripts/python.exe ops/doctor.py          # 人类可读
.venv/Scripts/python.exe ops/doctor.py --json   # 机器可读

# 跑批（两种等价方式）
curl -s -X POST http://127.0.0.1:8620/api/runs/trigger   # 经门户，留痕进历史
cd pipeline && ../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors  # 直接 dbt

# 重启门户（Windows 端口占用先杀旧进程，见手册故障 P-01）
for pid in $(netstat -ano | grep ":8620" | grep LISTENING | awk '{print $5}' | sort -u); do taskkill //F //PID $pid; done
(.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8620 > logs/uvicorn.log 2>&1 &)
```

## 你被指派任务时的第一动作

1. `ops/doctor.py --json` 看系统健康
2. 打开 docs/AI-操作手册.md 找对应"操作配方"章节——大部分任务有现成配方，照配方做
3. 配方没有的：先读相关模块 docstring，再动手；改完跑 doctor + 触发一次跑批验证
4. 提交到 develop 分支（main 只在人类验收后合并）；commit message 用中文、说清 why
