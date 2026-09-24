# AI 操作手册 — 明账 ClearLedger

> **读者**：AI agent（ZCode 或任何后继者）。你将独立维护、扩展、排障这套系统，人类只验收。
> **目标**：让你在不开口问人的前提下，安全完成 95% 的日常操作，并知道剩下 5% 该问什么。
> **约定**：本文按"认知 → 资产 → 配方 → 排障 → 自动化 → 红线"组织；每条配方都是可执行的。
> 根入口见 [AGENTS.md](../AGENTS.md)；业务口径见 [指标口径.md](指标口径.md)；决策与 why 见 [待确认与决策.md](待确认与决策.md)。

---

## 1. 系统地图（一页认知，v0.3 多账套）

```
              ┌─────────────── 人类世界 ────────────────┐
              │ 投放区 instances/<账套>/data/inbox/        │
              │ 浏览器 http://127.0.0.1:8620（顶栏切账套） │
              └──────────┬──────────────────▲─────────┘
                         │                  │ HTTP（全部 API 按账套路由）
┌────────────────────────▼──────────────┐   ┌┴─────────────────────────┐
│ semantic/ 引擎（零业务预设，永不随账套改）│   │ app/ 门户                  │
│ ingest_run.py  入口档案+字段契约→raw     │   │ main.py 按账套路由的 API    │
│ compile_dbt.py 五配置→dbt project 生成  │   │ dbt_runner.py 实例三步链   │
│ query.py       指标×维度→SQL 编译       │   │ settings.py 账套+跑批模式  │
└────────────────────────┬──────────────┘   │ static/ 原生JS门户         │
                         │                  └──────────────────────────┘
   instances/<账套>/                     每账套独立：
     五配置 yml（业务差异全在这）          data/warehouse/<账套>.duckdb
     pipeline/（生成物，进git勿手改）      data/runs/history_<账套>.json
```

**进程模型**：常驻进程只有 uvicorn（门户+调度器）。跑批 fork 三个子进程（ingest_run →
compile_dbt → dbt build），日志 logs/run_<账套>_<run_id>.log。全系统跑批互斥。

**红绿灯判定**：红 = 三步任一退出码非零或无本轮新鲜 run_results；黄 = dbt 测试 warn；
绿 = 全过。状态词汇两套（dbt 词汇 vs 灯色词汇），映射见 main.py 的 _STATUS_TO_LIGHT。

---

## 2. 状态资产清单（每个文件：谁写、含什么、可否删）

| 路径 | 谁写 | 内容 | 可否删 |
|---|---|---|---|
| `data/warehouse/<账套>.duckdb` | ingest + dbt | 该账套**全部业务数据**（raw/staging/intermediate/marts 四 schema），每账套一个文件 | ❌ 删=该账套数据清零，只能靠 inbox 重建 |
| `data/warehouse/<账套>.duckdb.wal` | DuckDB | 未 checkpoint 的写日志；存在时备份必须连它一起拷 | ⚠️ 不要手动删，checkpoint 后自动消失 |
| `instances/<账套>/data/inbox/` | 人类投放 | 该账套源数据文件（清单见该账套 sources.yml 的 patterns） | ⚠️ 数据源头，删了跑批红灯 |
| `data/runs/history_<账套>.json` | dbt_runner | 该账套跑批历史（最多 60 条，原子写）| 可删但丢失历史，排查能力降级 |
| `data/runs/<run_id>_run_results.json` | dbt_runner | 每轮归档的 dbt 产物 | ✅ 随 history 滚动自动清理 |
| `data/settings.json` | settings.py | 当前账套 + 跑批模式（默认手动）+ 定时时间 + ai_banner | ✅ 删了回到默认（手动模式） |
| `logs/run_<账套>_<run_id>.log` | 跑批子进程 | ingest+compile+dbt 全量输出（UTF-8，门户可看末 400 行） | ✅ 旧日志可清 |
| `logs/ingest_<账套>_last.json` | ingest_run | 最近一次摄取各源行数/成败/违规 | ✅ 每次跑批自动覆盖 |
| `logs/uvicorn.log` | 门户 | HTTP 访问 + 启动日志 | ✅ |
| `pipeline/target/manifest.json` | dbt | 全部模型结构+血缘+字典（800KB，门户缓存解析） | ✅ dbt 自动重建；**改模型后必须重跑 dbt** 它才更新 |
| `pipeline/target/run_results.json` | dbt | 最近一轮节点成败（红绿灯原料） | ✅ 同上 |
| `app/static/vendor/*.js` | 人类/AI 一次性下载 | ECharts/G6 本地副本（无外网依赖） | ❌ 删了页面崩，需重新下载 |
| `app/static/index.html` 的 `?v=` 串 | AI（你） | 静态资源缓存击穿版本号，**改前端必升** | — |

**两个易混淆点**：
- manifest.json 的 `columns`（yml 字典）与 information_schema 的 `data_type` 是两个来源，字典页合并展示；改 yml 描述后字典不会变，直到下一次 dbt build
- 血缘图读 manifest（结构）+ history（状态）合成；首轮未跑批时全灰属正常

## 3. 操作配方（按任务组织，照做即可）

### R-01 跑一次批并确认结果（v0.3 实例链路）
```bash
# 方式一：门户 API（推荐，自动带当前账套）
curl -s -X POST "http://127.0.0.1:8620/api/runs/trigger?instance=sales"
# 方式二：CLI 三步链
.venv/Scripts/python.exe -m semantic.ingest_run  --instance sales
.venv/Scripts/python.exe -m semantic.compile_dbt --instance sales
(cd instances/sales/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors)
.venv/Scripts/python.exe -m semantic.harvest --instance sales   # 匹配契约收获→挂起队列

sleep 30
curl -s "http://127.0.0.1:8620/api/overview" | python -c "import json,sys;d=json.load(sys.stdin);print(d['instance']['title'], d['light'], d['last_run']['counts'])"
```
各账套基线：sales 37 / restaurant 27 / retail 70（60绿10黄）/ hro 56（52绿4黄）/
ladder 61（56绿5勾稽，分层利润阶梯演示）。retail/hro 的 warn 是混沌条款预埋
（幽灵供应商/空键），属预期。_wb_r1 是 v0.6 测试专用账套（39 节点），不算正式基线。red 时去 §4 排障。

### R-02 新增/修改一个数据源（v0.3+ 配置驱动）
1. 人类把新文件放进 `instances/<账套>/data/inbox/`（文件名按 sources.yml 的 discover.patterns）
2. `instances/<账套>/sources.yml` 加一段：`name/title/discover.patterns/encodings/clean/fields`（fields 逐列声明 cn 中文名→map 英文列、type、required/enum/range/missing 契约与 level 定级——这是字段契约，写法照抄同文件现有源）
3. 若它参与宽表：在 `wide.yml` 的 joins 加一条（keys.left/right + columns 拉取列 + contract 定级）；维度列记得进 `dimensions.yml`
4. 跑 R-01 三步链验证；契约违规会进挂起队列（工作台「挂起队列」页），扇出/匹空由匹配契约测试收获
5. **空文件会显式报错**（设计决策 D7），提醒人类确认导出
6. 新文件名月度漂移不用改配置——discover.patterns 通配符扛住；表头变了才会 header_changed 红灯

### R-03 加一个指标（v0.3+ 配置驱动）
- `instances/<账套>/metrics.yml` 加一条：`{name, expr, desc}`——expr 只准引用宽表可见列（编译期悬空检查会指名道姓），desc 是界面可查的中文口径，**这是口径唯一出处**
- 想在报表里用它：把指标名加进 `dashboard.yml` 对应报表的 metrics 数组
- 生效方式：R-13 工作台「保存并重建」，或 agent 路重跑 compile_dbt + dbt build

### R-04 加一张报表 / 改看板卡片
- `instances/<账套>/dashboard.yml` 加一条报表：`{key, title, dimension, time_dim, metrics, filters?, chart}`（维度/指标必须已声明，编译期校验）
- 生效：重编译重跑（或工作台「保存并重建」）；门户报表页/字典/血缘自动出现，无需改前端
- 前端只在图表形态分支时才需要动 `reports.js` 的 drawChart（新图表类型才算技术活）

### R-05 改跑批模式 / 时间
```bash
# 开定时（每天 07:15）
curl -s -X POST http://127.0.0.1:8620/api/settings -H "Content-Type: application/json" \
  -d '{"schedule_enabled": true, "hour": 7, "minute": 15}'
```
持久化在 data/settings.json，重启生效。定时触发的是**当前账套**（settings.instance）。**手动模式（默认）下系统绝不自动跑批**——这是用户拍板的决策 D5，不要"顺手"改默认值。

### R-06 备份 / 恢复 / 迁移新机器
- 备份：跑 `备份数据.bat`（PowerShell 时间戳，连 .wal 一起，失败显式报错）
- 恢复：把 warehouse.duckdb 拷回 `data/warehouse/` 即可
- 迁移：整个目录拷走（含 .venv 可作废重建）→ 新机 `git clone` 或拷贝 → 从 GitHub Releases 下载 `启动明账.exe` 放仓库根目录双击（首次自动建 venv 装依赖+演示数据+首跑，见 R-12）

### R-07 重启门户（Windows）
```bash
for pid in $(netstat -ano | grep ":8620" | grep LISTENING | awk '{print $5}' | sort -u); do taskkill //F //PID $pid; done
(.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8620 > logs/uvicorn.log 2>&1 &)
```
改了任何 `app/` 下 Python 文件都需要重启（uvicorn 未开 --reload，性能考虑）。改 `app/static/` 只需刷新浏览器（记得升版本号）。

### R-10 MCP 接入配方（v0.4：让外部 agent 连明账）
明账作为 MCP server（stdio）对外提供六个只读工具：账套列表 / 指标目录 / 报表目录 /
查询报表 / 数据健康诊断（缺什么没导入）/ 单指标口径。全调用审计在 logs/mcp_audit.jsonl。

Claude Code 接入（~/.claude.json 或项目 .mcp.json）：
```json
{"mcpServers": {"clearledger": {
  "command": "<仓库>/.venv/Scripts/python.exe",
  "args": ["<仓库>/mcp_server.py"]}}}
```
ZCode 同理加进 MCP 配置。之后即可对 agent 说：
"明账里华东上月毛利多少？""这期报表为什么没出？"

HTTP 形态（不支持 MCP 的 agent）：`/api/open/*` + `X-API-Key` 头。
钥匙登记在 data/openapi_keys.json（不入 git；模板 openapi_keys.example.json，
key 用 python -c "import secrets;print(secrets.token_urlsafe(32))" 生成）。
```bash
curl -H "X-API-Key: <key>" "http://127.0.0.1:8620/api/open/reports/monthly_kpi/data?limit=5"
curl -H "X-API-Key: <key>" "http://127.0.0.1:8620/api/open/status"
```
安全边界：只读；只能查声明的维度×指标（汇总级出网由架构保证）；全调用留痕。

### R-11 装配线体检（v0.4：新账套接入第一步）
```bash
.venv/Scripts/python.exe -m semantic.inspect --instance <新账套名>
```
产出 instances/<名>/onboarding/：inspect_report.md（列画像/空值率/键列/
枚举候选/join 建议）+ config_draft.yml（五配置草案）。审核草案→补指标
公式与报表→转正五配置→R-01 三步链→红绿灯验收。约定：下划线开头的
实例目录是测试副本，永不视为正式账套。

### R-12 启动器 exe 与首开 AI 提醒（v0.4）

- **双击 `启动明账.exe`**（PyInstaller 单文件，从 GitHub Releases 下载，放在仓库根目录）：自动走完 点火指南 Step 1~6（venv→依赖→演示数据→首跑→门户→开浏览器）；已初始化过的环境秒开。杀端口、等就绪、`--smoke` 无头自测都在 `ops/launcher.py`。
- **改了 launcher.py 要重打包**：命令在 `ops/launcher.py` 文件头 docstring（pyinstaller + ico 生成）；产物 `启动明账.exe` **不进 git**，用 `gh release create launcher-<日期> 启动明账.exe` 发到 GitHub Releases（2026-09-25 用户拍板：二进制出库，仓库只留源码）。
- **首开 AI 提醒横幅**：新克隆首次打开门户会提示"明账是 AI-Native 的、如何让 agent 介入"，可勾选"下次不再提醒"（持久化在 `data/settings.json` 的 `ai_banner`）。随时在门户左侧「AI 接入」页查看指引/重开提醒。
- 退役资产：`启动明账.bat`、`重建演示数据.bat`（功能已并入 exe，git 历史可找回）；`备份数据.bat` 保留。
- **界面中文化别名层**（v0.4 收官）：`app/services/aliases.py` 从六份配置自动推导技术名→中文（源/清洗表←sources.title，宽表←主源标题，报表←dashboard.title，字段←cn/维度名），经 `/api/aliases` 供前端 `App.alias()/falias()` 用。改配置标题即自动生效，别名层只做展示不改数据层命名。

### R-13 配置工作台（v0.5：改配置的两条等价路）

- **门户路**：左侧「配置工作台」→ 选块 → 改 YAML → 「校验」（引擎全套交叉校验，零落盘）→ 「保存」（旧文件自动备份到 `onboarding/config_history/<block>.prev.yml`）→ 需要生效就「保存并重建」（触发三步链，trigger=workbench）。
- **agent 路**：直接改 `instances/<账套>/*.yml` → 重跑 compile_dbt + dbt build（与以前完全一样）。两条路等价：工作台的"保存并重建"就是 agent 路的自动化。
- **挂起队列**：工作台「挂起队列」页 = 最近一次 run 的契约违规清单（raw.contract_report 稳定投影）。处理：修数据重投 → 重新跑批；或放宽字段契约 level 后保存并重建。
- **影响预览**：保存 metrics/dashboard 时响应带 affected_reports（哪些报表引用了草稿里的指标/被改动）；也可单独 GET `/api/config/<账套>/impact`。
- **回滚**：单步回滚用 `config_history/<block>.prev.yml` 覆回去再重建；跨版本回滚靠 git。
- API 契约全文：`docs/设计-v0.5-配置工作台.md`。红线不因工作台改变：models 是生成物禁手改，口径唯一出处仍是 metrics.yml。

### R-08 更新演示数据
启动器 **`启动明账.exe`** 的「重建演示数据」按钮，或分步：`sample_data/generate.py` → `semantic.ingest_run` → `semantic.compile_dbt` → cd pipeline && dbt build（详见 docs/AI-点火指南.md Step 3/4）。
生成器特性：截止昨天动态生成；**预埋 2026-05 华东断供异常**（所以黄灯是预期，不是 bug）；300 行客户编号带首尾空格（清洗层演示）。

### R-09 语义层实例操作（v0.3 配置驱动，推荐路径）
实例 = `instances/<名字>/` 五配置 + 独立库。全链路三步：
```bash
.venv/Scripts/python.exe -m semantic.ingest_run   --instance <名字>   # 摄取+契约校验（red→退出1）
.venv/Scripts/python.exe -m semantic.compile_dbt  --instance <名字>   # 配置→dbt project（输出diff摘要）
cd instances/<名字>/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors
```
查询编译器：`.venv/Scripts/python.exe -m semantic.query <实例> [报表key] [--filter 维度=值]`。
要点：
- 契约违规留痕在实例库 `raw.contract_report`（按 run_id 追溯）；多文件命中取 mtime 最新并黄灯留痕
- 改任何 yml 后必须重跑 compile（生成物进 git，提交前看 diff 摘要）
- 双实例物理隔离：`data/warehouse/<实例>.duckdb` 各自独立；引擎 `semantic/` 零业务预设，**为适配新公司改引擎=设计违规**
- 新公司接入 = 复制 instances/sales 起草五配置（AI 主笔）→ R-09 三步 → 对照对数
- 悬空引用（指标/派生列引用不存在的列、报表引用未知指标维度）在 compile 期被 ConfigError 指名道姓拦下

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

1. **口径唯一出处**：`instances/<账套>/metrics.yml` 与 wide.yml 派生列是口径的家；前端/查询编译器之外任何地方重算 = 事故
2. **原始层只增不改**：raw schema 是源文件镜像（含 _source_file/_loaded_at 溯源列），任何"清洗"发生在 staging
3. **测试即契约**：每账套 27~61 个节点里的测试（match/range/recon 系列）是产品的一部分；删测试比改错代码更严重。warn 测试是黄灯的来源，动它要更新指标口径.md 的红绿灯表
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

## 8. 路线图衔接

v0.3「通用积木」已落地（本手册 R-02/R-03/R-04 即配置驱动现状）；v0.4 开放接口与体检器已落地（R-10/R-11）；
v0.5 配置工作台已落地（R-13）。当前进行中：勾稽护栏（已上线）→ 指标阶梯 → 时间智能 → 分摊引擎
（用户 2026-09-21 圈选，见 docs/决策-20260921-层级功能与运行视图.md）。测试账套约定：下划线开头=
测试副本；ladder=分层演示账套。
