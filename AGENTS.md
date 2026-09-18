# AGENTS.md — AI 代理接管入口

> 你（AI agent）被派来维护/扩展这个项目时，**从本文件开始**。
> 本项目第一性原则：**AI-Native**——系统的第一读者和第一操作者都是 AI，
> 人类只做验收与拍板。因此本文档的存在本身就是产品需求，不是附赠品。

## 30 秒认知

- 项目：**明账 ClearLedger**——私有化管理报表数据底座（DuckDB + dbt + FastAPI + 原生 JS 门户）
- 平台：Windows 本机，Git Bash，Python venv 在 `.venv/`（Windows 路径 `.venv\Scripts\`）
- 门户：`http://127.0.0.1:8620`（仅本机监听，无认证——有意为之，见决策 D4）
- **多账套架构（v0.3 起）**：一个公司 = `instances/<账套>/` 下五份配置（sources/wide/dimensions/metrics/dashboard）+ 独立库 `data/warehouse/<账套>.duckdb`。引擎 `semantic/` 零业务预设。内置账套：sales（演示销售公司）、restaurant（演示连锁餐饮）、retail（零售进销存·测试）、hro（人力外包·测试）
- 数据流：`instances/<账套>/data/inbox/` → `semantic.ingest_run`（三契约校验）→ `semantic.compile_dbt`（配置→dbt project）→ dbt build → 门户按账套路由
- 当前状态：main=develop（v0.3 收官：语义引擎+账套切换+旧手写管道退役）；下一站 v0.5 配置工作台与挂起队列

## 必读文件（按顺序）

1. **docs/AI-操作手册.md** — 系统地图、状态资产清单、操作配方、故障 playbook、你的自动化 SOP
2. docs/指标口径.md — 业务口径基础域定义（各账套口径以各自 instances/<账套>/metrics.yml 为唯一出处）
3. docs/待确认与决策.md — 所有已拍板决策与红线（D1~D15），不要推翻已有决策
4. docs/迭代日志.md — 历史教训库（前人踩过的坑，按时间组织；手册里按症状重新组织过）

## 红线（违反 = 事故）

- **口径唯一出处**：指标计算只允许存在于 `instances/<账套>/metrics.yml` 与 wide.yml 派生列，报表层与前端只引用不重算
- **报表只读 marts 层**：查询编译器（semantic/query.py）只查 marts，不许碰 staging/raw
- **改任何 instances/<账套>/yml 后必须重跑** `-m semantic.compile_dbt --instance <账套>` + dbt build（当前基线：sales 37 / restaurant 27 / retail 70 / hro 56 节点，retail/hro 的 warn 是混沌条款预埋，属预期）
- **instances/<账套>/pipeline/models 是生成物，禁止手改**——要改就改 yml 配置重新编译
- **改前端静态文件必须升版本号**：`app/static/index.html` 里的 `?v=YYYYMMDDx` 串，否则浏览器用旧缓存——这是真实踩过的坑
- **Git Bash 里禁止 `>nul` 重定向**（会创建名为 nul 的真实文件导致 git add 崩溃，已两次踩坑）；静默输出用 `>/dev/null`
- **跑批期间仓库带写锁**：直接查 DuckDB 用只读连接 + 重试（参考 semantic/query.py 的 _connect）
- **YAML 配置键禁用 on/off/yes/no**（YAML 1.1 布尔字面量坑，join 键因此叫 keys）
- data/ 与 logs/ 不入 git；`data/warehouse/<账套>.duckdb` 是该账套全部业务数据，动它之前先跑 备份数据.bat

## 快速命令

```bash
# 自检（你应该在动手前先跑这个）
.venv/Scripts/python.exe ops/doctor.py          # 人类可读
.venv/Scripts/python.exe ops/doctor.py --json   # 机器可读

# 某账套跑批（三步链；门户"立即跑批"按钮等价）
.venv/Scripts/python.exe -m semantic.ingest_run  --instance sales
.venv/Scripts/python.exe -m semantic.compile_dbt --instance sales
(cd instances/sales/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors)

# 查询编译器
.venv/Scripts/python.exe -m semantic.query sales region_month --filter 区域=华东

# 重启门户（Windows 端口占用先杀旧进程，见手册故障 P-01）
for pid in $(netstat -ano | grep ":8620" | grep LISTENING | awk '{print $5}' | sort -u); do taskkill //F //PID $pid; done
(.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8620 > logs/uvicorn.log 2>&1 &)
```

## 你被指派任务时的第一动作

1. `ops/doctor.py --json` 看系统健康
2. 打开 docs/AI-操作手册.md 找对应"操作配方"章节——大部分任务有现成配方，照配方做
3. 配方没有的：先读相关模块 docstring，再动手；改完跑 doctor + 触发一次跑批验证
4. 提交到 develop 分支（main 只在人类验收后合并）；commit message 用中文、说清 why
