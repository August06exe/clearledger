# AI 操作手册 — 明账 ClearLedger

> **读者**：AI agent（ZCode 或任何后继者）。你将独立维护、扩展、排障这套系统，人类只验收。
> **目标**：让你在不开口问人的前提下，安全完成 95% 的日常操作，并知道剩下 5% 该问什么。
> **约定**：本文按"认知 → 资产 → 配方 → 排障 → 自动化 → 红线"组织；每条配方都是可执行的。
> 根入口见 [AGENTS.md](../AGENTS.md)；业务口径见 [指标口径.md](指标口径.md)；决策与 why 见 [待确认与决策.md](待确认与决策.md)。

---

## 1. 系统地图（一页认知）

```
                    ┌────────────────────────── 人类世界 ──────────────────────────┐
                    │  把 Excel/CSV 放进 data/inbox/  ←→  浏览器 http://127.0.0.1:8620  │
                    └──────────┬───────────────────────────────▲──────────────────┘
                               │ 文件                           │ HTTP
┌──────────────────────────────▼───────────────┐   ┌───────────┴──────────────────┐
│ ingest/ingest.py（摄取器）                    │   │ app/（门户）                  │
│ 读 ingest/sources.yml 声明的 5 个数据源        │   │ main.py  FastAPI 全部 API     │
│ 清洗→列名标准化→raw schema（全量快照覆盖）      │   │ services/ 业务逻辑            │
└──────────────────┬───────────────────────────┘   │  duck.py       查询(带锁重试) │
                   │ 写 warehouse.duckdb           │  dbt_runner.py 跑批执行器      │
┌──────────────────▼───────────────────────────┐   │  artifacts.py dbt产物解析     │
│ pipeline/（dbt 三层管道，55 节点）             │   │  lineage.py    血缘(表级+字段级)│
│ raw → staging(清洗) → intermediate(口径)      │   │  reports.py    报表注册表      │
│        → marts(报表层，只许报表读)             │   │  settings.py   跑批模式开关    │
│ 每次跑批产出 manifest.json + run_results.json │   │ static/  原生JS门户(ECharts/G6)│
└──────────────────┬───────────────────────────┘   └───────────▲──────────────────┘
                   │ 读写 warehouse.duckdb                     │ APScheduler
                   └───────────────────► data/warehouse/ ◄─────┘（仅定时模式开启时）
```

**进程模型**：常驻进程只有一个——uvicorn（门户+调度器）。跑批时它 fork 两个子进程
（ingest.py、dbt.exe），子进程日志追加写入 `logs/run_<run_id>.log`。DuckDB 单写者：
跑批期间（约 8 秒）门户查询靠 `duck.py` 的 20×0.5s 重试熬过去。

**关键判定逻辑（你必须理解，这是红绿灯的灵魂）**：
- 红 = 摄取失败（缺文件/表头变了/空文件）或 dbt 返回码≠0 或 run_results.json 不是本轮新产物（mtime 校验，防"假绿灯"）→ 下游拦截 + 报表挂"数据过期"横幅
- 黄 = dbt build 整体成功但存在 severity=warn 的测试（如区域收入环比骤降>50%）
- 绿 = 全部通过
- 状态词汇两套：dbt 词汇（success/pass/warn/fail）在 run 明细里；**灯色词汇（green/yellow/red）**在 `/api/lineage/graph` 里（`_STATUS_TO_LIGHT` 归一化）——新增状态映射时两套都要对齐

## 2. 状态资产清单（每个文件：谁写、含什么、可否删）

| 路径 | 谁写 | 内容 | 可否删 |
|---|---|---|---|
| `data/warehouse/warehouse.duckdb` | ingest + dbt | **全部业务数据**（raw/staging/intermediate/marts 四 schema） | ❌ 删=数据清零，只能靠 inbox 重建 |
| `data/warehouse/warehouse.duckdb.wal` | DuckDB | 未 checkpoint 的写日志；存在时备份必须连它一起拷 | ⚠️ 不要手动删，checkpoint 后自动消失 |
| `data/inbox/` | 人类投放 | 源数据文件（5 个，清单见 ingest/sources.yml） | ⚠️ 这是数据源头，删了跑批红灯 |
| `data/runs/history.json` | dbt_runner | 跑批历史（最多 60 条，原子写）| 可删但丢失历史，排查能力降级 |
| `data/runs/<run_id>_run_results.json` | dbt_runner | 每轮归档的 dbt 产物 | ✅ 随 history 滚动自动清理 |
| `data/settings.json` | settings.py | 跑批模式（默认手动）+ 定时时间 | ✅ 删了回到默认（手动模式） |
| `logs/run_<run_id>.log` | 跑批子进程 | ingest+dbt 全量输出（UTF-8，门户可看末 400 行） | ✅ 旧日志可清 |
| `logs/ingest_last.json` | ingest.py | 最近一次摄取各源行数/成败 | ✅ 每次跑批自动覆盖 |
| `logs/uvicorn.log` | 门户 | HTTP 访问 + 启动日志 | ✅ |
| `pipeline/target/manifest.json` | dbt | 全部模型结构+血缘+字典（800KB，门户缓存解析） | ✅ dbt 自动重建；**改模型后必须重跑 dbt** 它才更新 |
| `pipeline/target/run_results.json` | dbt | 最近一轮节点成败（红绿灯原料） | ✅ 同上 |
| `app/static/vendor/*.js` | 人类/AI 一次性下载 | ECharts/G6 本地副本（无外网依赖） | ❌ 删了页面崩，需重新下载 |
| `app/static/index.html` 的 `?v=` 串 | AI（你） | 静态资源缓存击穿版本号，**改前端必升** | — |

**两个易混淆点**：
- manifest.json 的 `columns`（yml 字典）与 information_schema 的 `data_type` 是两个来源，字典页合并展示；改 yml 描述后字典不会变，直到下一次 dbt build
- 血缘图读 manifest（结构）+ history（状态）合成；首轮未跑批时全灰属正常

## 3. 操作配方（按任务组织，照做即可）

### R-01 跑一次批并确认结果
```bash
curl -s -X POST http://127.0.0.1:8620/api/runs/trigger   # 返回 run_id
sleep 25                                                  # 完整跑批约 8~15s，留余量
curl -s http://127.0.0.1:8620/api/overview | python -c "import json,sys;d=json.load(sys.stdin);print(d['light'],d['last_run']['counts'])"
# 预期：yellow（55 节点：12 success + 42 pass + 1 warn）——那 1 个 warn 是预埋演示异常，属预期
```
判断标准：green/yellow 都算"数据可用"；red 时去 §4 排障。**不要用 CLI 直跑 dbt 代替 API 触发**——会绕过运行历史留痕。

### R-02 新增/修改一个数据源（最常见任务）
1. 人类把新文件放进 `data/inbox/`
2. `ingest/sources.yml` 加一段：`name/title/format/files/column_map(中文表头→英文snake_case)/date_columns/numeric_columns`
3. `pipeline/models/staging/` 加 `stg_<name>.sql`（照抄现有 5 个的模式：trim 关键列、强类型、where 剔坏行）+ 在 `sources.yml`(staging 的) 声明 source + `_staging.yml` 加字典与测试（not_null/unique/relationships 至少各一）
4. 若它参与宽表：进 `int_sales_enriched.sql` 关联（v0.5 后此步变为 wide.yml 配置）
5. 跑 R-01 验证；门户字典页应出现新表
6. **空文件会显式报错**（设计决策 D7：宁可不跑也不跑错），提醒人类确认导出

### R-03 加一个指标（当前版本；v0.5 后改配置）
- 计算逻辑 → intermediate 层加列（口径唯一出处），`_intermediate.yml` 补字典
- 报表展示 → `app/services/reports.py` 的 REPORTS 注册表加一项（columns 列表 + run 函数，参数必须走 `_as_int/_in_whitelist` 白名单，**禁止字符串直拼 SQL**）

### R-04 加一张报表 / 改看板卡片
- 新报表：reports.py 注册表 + `static/js/pages/reports.js` 的 drawChart 加分支（注意：这是已知技术债，v0.5 配置化后消失）
- 总览 KPI 卡：`static/js/pages/overview.js` 的 kpiCard 调用处；**环比一律引用 mart 的 *_mom 字段，前端不许重算**（口径唯一出处原则）

### R-05 改跑批模式 / 时间
```bash
# 开定时（每天 07:15）
curl -s -X POST http://127.0.0.1:8620/api/settings -H "Content-Type: application/json" \
  -d '{"schedule_enabled": true, "hour": 7, "minute": 15}'
```
持久化在 data/settings.json，重启生效。**手动模式（默认）下系统绝不自动跑批**——这是用户拍板的决策 D5，不要"顺手"改默认值。

### R-06 备份 / 恢复 / 迁移新机器
- 备份：跑 `备份数据.bat`（PowerShell 时间戳，连 .wal 一起，失败显式报错）
- 恢复：把 warehouse.duckdb 拷回 `data/warehouse/` 即可
- 迁移：整个目录拷走（含 .venv 可作废重建）→ 新机 `git clone` 或拷贝 → 双击 `启动明账.bat`（首次自动建 venv 装依赖）→ `重建演示数据.bat`（若要演示数据）

### R-07 重启门户（Windows）
```bash
for pid in $(netstat -ano | grep ":8620" | grep LISTENING | awk '{print $5}' | sort -u); do taskkill //F //PID $pid; done
(.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8620 > logs/uvicorn.log 2>&1 &)
```
改了任何 `app/` 下 Python 文件都需要重启（uvicorn 未开 --reload，性能考虑）。改 `app/static/` 只需刷新浏览器（记得升版本号）。

### R-08 更新演示数据
`重建演示数据.bat` 或分步：`sample_data/generate.py` → `ingest/ingest.py` → cd pipeline && dbt build。
生成器特性：截止昨天动态生成；**预埋 2026-05 华东断供异常**（所以黄灯是预期，不是 bug）；300 行客户编号带首尾空格（清洗层演示）。

## 4. 故障排查 Playbook（按症状查）

### 症状：总览红灯
1. `curl -s http://127.0.0.1:8620/api/runs | head` 取最新 run_id → `curl .../api/runs/<run_id>` 看 `error` 字段与 `ingest.results`
2. 三种红灯，处置不同：
   - **摄取失败**（最常见）：error 写明缺哪个文件/哪列表头变了 → inbox 文件被改名？源系统改导出格式？→ 修文件或改 sources.yml 的 column_map
   - **dbt 返回码≠0 有产物**：某模型/测试 error → run 明细里找 status=fail 的节点看 message，通常是 SQL 改错了
   - **dbt 崩溃无产物**：看 `curl .../api/runs/<run_id>/log?tail=200`，通常是 profiles/依赖/磁盘问题
3. 修复后跑 R-01 确认回到 yellow/green；红灯期间报表页挂着"数据过期"横幅（预期行为，不是 bug）

### 症状：门户打不开（连接拒绝）
- P-01 端口占用 `10048`：R-07 杀旧进程重启（旧 uvicorn 没死透，**重启后必须验证新进程真的起来了**——看 uvicorn.log 尾部是否 "Application startup complete"，上次就因为没验证导致测了半天旧代码）
- 进程不存在：直接 R-07 启动

### 症状：数据/页面"不对劲"
- 页面行为怪异 → **先强刷**（Ctrl+F5 / 换 `?fresh=N` 参数）。静态缓存是真实踩过的坑（P-03）
- 图表空白 → F12 看控制台；G6 图实例可 `window.__clGraph` 直查
- 跑批期间查询 503 → 预期（锁等待上限 10s），跑完自动恢复

### 症状：日志乱码
子进程已注入 PYTHONUTF8=1（教训 P1-2）。若你在新代码里 subprocess，**必须沿用 dbt_runner.run_cmd 的 env 模式**。

### 症状：git add 报 `unable to index file 'nul'`
Git Bash 下 `>nul` 会创建真实文件。`rm -f nul` 删掉，以后用 `>/dev/null`。已两次踩坑。

## 5. Agent 自动化 SOP（你的标准作业程序）

### 5.1 健康巡检（可定时执行）
```bash
.venv/Scripts/python.exe ops/doctor.py --json
```
输出机器可读的 12+ 项检查（环境/仓库/端口/跑批/配置完整性）。`status=ok` 即系统健康；
任何 `fail` 项按 §4 对症处置。

### 5.2 红灯自愈循环（收到"处理一下红灯"类任务时）
1. doctor --json 确认门户活着
2. 取最新 run → error 字段 + log tail=200 → 按 §4 三分法定位
3. **能自动修的**（文件改名/表头映射/明显 SQL 笔误）：修复 → 跑 R-01 → 确认回黄/绿 → 提交 develop（commit 说明 root cause）
4. **不能自动修的**（缺源文件、口径争议）：停在诊断结论，产出一段"给人类的说明"（症状/原因/需要你做什么），**不要编数据或绕过测试让灯变绿**——红绿灯的可信度高于一切

### 5.3 代码改动后的固定验收序列
```bash
cd pipeline && ../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors | tail -3
# 预期末行：Done. PASS=54 WARN=1 ERROR=0 ... TOTAL=55（数字变了要能解释为什么）
cd .. && .venv/Scripts/python.exe ops/doctor.py
curl -s -X POST http://127.0.0.1:8620/api/runs/trigger && sleep 25 && curl -s http://127.0.0.1:8620/api/overview
```
前端改动额外：升版本号 → 浏览器强刷实测（截图目检，canvas 图表 DOM 快照看不见）。

### 5.4 API 面（GET 只读安全 / POST 会改变状态）
- 只读：`/api/overview` `/api/lineage/graph` `/api/lineage/columns/{model}` `/api/node/{uid}` `/api/dictionary` `/api/reports` `/api/reports/{key}/data?months=N` `/api/runs` `/api/runs/status` `/api/runs/{id}` `/api/runs/{id}/log?tail=N` `/api/settings`
- 改状态：`POST /api/runs/trigger`（409=已有跑批在跑）、`POST /api/settings`、`GET /api/reports/{key}/export`（生成下载）
- 报表参数注入安全：后端白名单校验（`_in_whitelist/_as_int`），你写新报表时必须沿用

### 5.5 夜航模式（长时自主开发）
人类会说"开工/夜航"。此时你：develop 分支 → 里程碑式小步提交 → **独立审计 agent 循环**
（调研→spawn 只读 Explore agent 审计→对照需求确认→修复→记录进迭代日志.md）→
浏览器实测 → 晨间汇报（结论先行、待拍板清单）。完整范式参考迭代日志第 0~2 轮。

## 6. 红线与纪律（违反=事故，人类验收时会一眼看出）

1. **口径唯一出处**：§1 图里 intermediate 层是口径的家；前端/reports.py 重算 = 事故
2. **原始层只增不改**：raw schema 是源文件镜像（含 _source_file/_loaded_at 溯源列），任何"清洗"发生在 staging
3. **测试即契约**：55 节点里 43 个测试是产品的一部分；删测试比改错代码更严重。warn 测试是黄灯的来源，动它要更新指标口径.md 的红绿灯表
4. **决策不推翻**：docs/待确认与决策.md 的 D1~D13 是人类拍过板的（如 Dagster 砍掉、默认手动跑批、仅本机监听），要改先问
5. **数据不编造**：5.2 的第 4 条，值得单独重复
6. **提交规范**：develop 分支、中文 commit、why 优先；main 只在人类验收后合并
7. **改完必验**：没有跑过 R-01 + doctor 的改动不算完成

## 7. 历史教训 TOP 8（提炼自迭代日志，防复发）

| # | 教训 | 现行防线 |
|---|---|---|
| 1 | dbt 崩溃不写产物时，读旧 run_results 会"假绿灯" | 返回码+产物 mtime 双校验；改 dbt_runner 判定逻辑时**必须重读这段** |
| 2 | 红灯只拦管道不拦报表=半闭环 | stale 字段+横幅+Excel 警示行；改报表 API 时别弄丢 stale |
| 3 | 中文 Windows 子进程输出 GBK 乱码 | run_cmd 的 env 注入模式；bat 里 set PYTHONUTF8=1 |
| 4 | APScheduler 默认 misfire 宽限 1 秒，错过的定时跑静默丢失 | 6h 宽限+coalesce+启动补跑（仅定时模式） |
| 5 | 零收入月 inner join 让总部费用蒸发、净利虚高 | 月×区域骨架+均摊兜底；改 int_expense_alloc 前读懂注释 |
| 6 | G6 fitView 在布局前执行→图放大 411% | afterlayout 后 fitView；新图组件同样处理 |
| 7 | 前端两套状态词汇不统一→节点全灰 | _STATUS_TO_LIGHT 归一化；加状态时两套映射都改 |
| 8 | Git Bash `>nul` 创建真实文件→git add 崩溃 | 用 >/dev/null；.gitignore 已兜底 nul |

## 8. 与路线图的衔接（v0.5 积木化对本手册的影响）

已定的方向（见与用户的讨论）：业务层从写死代码改为**五份配置**——sources.yml（已有）、wide.yml（声明式宽表：主表+左联标签表+派生列）、dimensions.yml、metrics.yml、dashboard.yml；引擎永不随公司变；**AI 的角色=读源文件+问答→生成五份配置→人类审核**。落地后：
- R-02/R-03/R-04 将从"改代码"降级为"改配置"（本手册相应章节会重写）
- 将新增"配置生成 SOP"章节（含第二实例=虚构连锁餐饮的验证标准）
- 摄取原则已由用户定调：**入库即干净字段**，原始快照仅作底账（清洗镜像层），报表只见干净层
