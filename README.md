<div align="center">

<img src="docs/assets/logo_B.png" width="72" alt="明账 logo" />

# 明账 ClearLedger

**每个数字，表里如一。—— AI Native 的管理报表数据底座**

把杂乱的 Excel/CSV 投放，变成有治理、可追溯血缘的管理报表——几乎全部由配置装配而成。

[![License: MIT](https://img.shields.io/badge/License-MIT-2563EB.svg)](LICENSE)
[![Status](https://img.shields.io/badge/状态-开发中·抢鲜体验-F59E0B.svg)](#-更新计划)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](https://python.org)
[![Engine](https://img.shields.io/badge/引擎-DuckDB%20%2B%20dbt-8B5CF6.svg)](#️-架构一页看懂)
[![MCP](https://img.shields.io/badge/MCP-只读开放-0D9488.svg)](#-让你的ai-agent连上来)
[![English](https://img.shields.io/badge/README-English-2563EB.svg)](README.en.md)

中文 · [English](README.en.md)

<img src="docs/assets/cover-c.png" width="100%" alt="明账 ClearLedger —— 从混乱表格到治理报表" />

</div>

---

> [!NOTE]
> **当前为开发中版本（抢鲜体验 Early Access）**。已有 4 个真实运转的公司账套实例
> （销售 / 连锁餐饮 / 零售进销存 / 人力外包），跑批红绿灯治理完整。更新计划见[文末](#-更新计划)。

## 🎯 为什么做明账

大家好，我是明账的作者。

我在公司做业务规划，平时的活儿就是把想法变成数字、再把数字讲给老板听。

去年新项目要做经营报表。这活儿的正经做法其实是清楚的：数据入 DuckDB，转换用 dbt，口径写成模型，报表挂个看板。工具都是现成的、开源的，我自己也折腾得动。

但真要自己养一套：管道要人跑，配置要人改，报错要人查，每一样都是持续的运维活儿。对多数只想把报表做出来的人来说不划算，于是需求提给产研，排期一排就是一年以后。

在那之前，我用 PowerBI、Alteryx、帆软 FDL 这类低代码平台搭过自动化。能跑，但非常不 AI native：东西存在它们自己的画布和私有格式里，AI 读不了也改不了，每次调整还是得人上。后来也试过直接让 agent 写脚本做自动化，结果踩了另一头的坑：上下文一长它就忘事，偶尔还不听话，数据悄悄算错。报表这个场景，错数是不可接受的。写死脚本倒是稳，可流程成了黑盒，卡在哪儿、数据从哪儿来，全靠翻代码。

明账就是为这个处境做的：

| | 低代码平台 | 纯 agent 自动化 | 手写脚本 | 明账 |
|---|---|---|---|---|
| AI 直接读写 | ❌ 私有画布格式 | ⚠️ 能写，但可能擅改 | ⚠️ 重构风险大 | ✅ 六份纯文本配置 |
| 数据可靠性 | ✅ | ❌ 丢上下文、不听指挥 | ✅ | ✅ 口径沉淀在系统，不靠 agent 记性 |
| 流程可视化 | ⚠️ 有，内部黑盒 | ❌ | ❌ | ✅ 红绿灯 + 血缘，卡点一眼可见 |
| 换新项目成本 | 高，重画 | — | 高，重写 | 低，换六份配置 |

它的做法是把工程活儿标准化成六份配置文件：数据源、宽表、维度、指标、看板、权限。全部是纯文本 YAML，agent 可以直接读、直接改，人也可以。新项目来了，换六份配置就能跑，引擎一行不动。日常你丢文件、定口径、看红绿灯；搭管道、改配置、修报错，都是 agent 的事。口径有唯一出处，数据有血缘，进库有契约，工程上的规矩一条没少，只是不用你亲手伺候。

<div align="center">
<img src="docs/assets/flow-governance.png" width="96%" alt="每批数据的必经之路：投放、三层契约校验、跑批、红绿灯、报表" />
<sub>每批数据的必经之路：投放 → 三层契约 → 跑批 → 红绿灯。灯色就是治理本身。</sub>
</div>

如果你：

- 每月花好几天拼 Excel 报表，口径一改就重做
- 报表需求提给产研，排期很远，业务等不起
- 新项目或新业务线，主系统暂时覆盖不到，想先把数据看板跑起来
- 口径散落在个人手里，人一休假报表就断

不妨来试试明账。

项目目前还在早期：内置四个演示账套，"投放、校验、跑批、报表、血缘"这条链路都能跑，离成熟产品还有距离。能力边界和更新计划见文末，欢迎来提 Issue。

## 📸 产品实拍

| 总览 · 红绿灯 | 血缘蜘蛛网（可下钻到字段级） |
|---|---|
| ![总览](docs/assets/screenshot-overview.png) | ![血缘](docs/assets/screenshot-lineage.png) |

| 管理报表 · 一键导出 | 指标口径 · 界面可查 |
|---|---|
| ![报表](docs/assets/screenshot-reports.png) | ![口径](docs/assets/screenshot-caliber.png) |

## ⚙️ 架构（一页看懂）

```mermaid
flowchart TD
    A["📥 Excel / CSV 投放区<br/>（每账套独立）"] -->|"摄取<br/>+ 字段契约"| B[("🦆 DuckDB<br/>每账套一个库文件")]
    B -->|"编译<br/>（配置 → dbt project）"| C["🔧 dbt 管道<br/>清洗 → 加工 → 报表层"]
    C --> D["📊 语义层<br/>metrics.yml = 口径唯一出处"]
    D --> E["🖥 一体化门户<br/>报表 · 血缘 · 字典 · 红绿灯"]
    F["🧩 六块积木配置<br/>sources · wide · dimensions · metrics · dashboard · permissions"] -.->|驱动| A
    F -.->|驱动| C
    F -.->|驱动| D
    F -.->|驱动| E
    G["🤖 AI 装配线<br/>读文件 → 起草配置 → 人审核"] -.-> F
    H["🔌 MCP 服务<br/>（只读 · 全程审计）"] --> E
```

**引擎（semantic/）零业务预设**。一切随公司变化的东西，收敛为每账套的**六块配置积木**——
引擎通用，装配交给 AI。

## 🧱 六块积木

<div align="center">
<img src="docs/assets/info-blocks-v5.png" width="96%" alt="六份配置，一台引擎：文件进，口径与报表出" />
<sub>六份纯文本配置，一台通用引擎——换公司换配置，引擎一行不动。</sub>
</div>

| 积木 | 文件 | 管什么 |
|---|---|---|
| ① 数据源 | `sources.yml` | 文件发现模式（扛月度改名）、清洗管道、字段契约（类型/范围/枚举/缺失策略）、问题定级 |
| ② 宽表 | `wide.yml` | 声明式关联（有序左联+匹配契约：扇出/匹空/孤儿）+ 派生列 |
| ③ 维度 | `dimensions.yml` | 哪些列变成可切片的维度（下钻/筛选/分组——零预设） |
| ④ 指标 | `metrics.yml` | 口径唯一出处：指标 = 一条公式 + 一段界面可查的中文说明 |
| ⑤ 看板 | `dashboard.yml` | 报表 = 维度 × 指标 × 筛选 × 图表 |
| ⑥ 权限 | `permissions.yml` | *（v0.7 规划）* 行列级访问，人与 API 钥匙统一主体 |

**三层数据契约**每批必查：入口档案（扛文件名月度漂移的发现模式、有序清洗原语、逐类问题定级）、
字段契约（摄取即校验，违规留痕 `raw.contract_report`）、匹配契约（扇出→红灯测试、匹空→黄灯+清单）。

换公司 = 换配置。引擎的 `git diff` 必须为零——这是硬验收闸门。

## 🚀 快速开始

明账是 AI-Native 的：配置与管道的搭建维护，本来就设计为交给 agent 做。三种点火方式，从省心到硬核（都需要本机装有 Python 3.11+）：

**方式一：交给你的 AI agent（推荐）**

把仓库交给任意 coding agent（ZCode / Claude Code / Cursor…），在仓库根目录对它说：

> 读取 docs/AI-点火指南.md，把我跑起来。

它会自己走完：环境自举 → 演示数据 → 首次跑批 → 门户验收，每步有检查点。这也是本项目的正确用法——之后换真实数据、改口径、修报错，同样都交给它。

**方式二：双击 `启动明账.exe`（Windows）**

图形引导窗自动完成同样的事，最后打开浏览器 `http://127.0.0.1:8620`。首次约 10–25 分钟（下载依赖），之后秒开。个别杀软可能对单文件 exe 误报，放行即可——源码就是本仓库，可自行审查。

**方式三：裸命令**

<details>
<summary>手动执行（等价于 agent 做的事）</summary>

```bash
git clone https://github.com/August06exe/clearledger.git
cd clearledger
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # Windows

# 生成两套演示账套数据（销售公司 + 连锁餐饮）并跑通全链路
.venv/Scripts/python sample_data/generate.py
.venv/Scripts/python sample_data/generate_restaurant.py
.venv/Scripts/python -m semantic.ingest_run  --instance sales
.venv/Scripts/python -m semantic.compile_dbt --instance sales
cd instances/sales/pipeline && ../../.venv/Scripts/dbt.exe build --profiles-dir . && cd ../../..

# 启动门户
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8620
# 浏览器打开 http://127.0.0.1:8620
```

</details>

> 门户打开后，首屏横幅会提示如何让你的 agent 介入（也可在左侧「AI 接入」页随时查看）。

## 📖 用法指南：明账的一天

跑起来之后，日常只有三件事是你的，其余都是 agent 的。

**① 丢文件（每月或每天）**

把业务系统导出的 Excel/CSV 丢进对应账套的投放区 `instances/<账套>/data/inbox/`。
文件名每月变（`销售明细2026-09.xlsx` → `…2026-10…`）没关系，入口档案的发现模式扛得住；
缺文件、格式漂移会在摄取时被字段契约拦下留痕，不会悄悄进库。

**② 跑批，看灯**

门户右上「▶ 立即跑批」，或用 ⏰ 设置改成每天定时（关机错过、开机补跑）。跑完看总览灯色：

| 灯色 | 含义 | 你做什么 |
|---|---|---|
| 🟢 绿 | 全部通过，报表已出 | 直接用 |
| 🟡 黄 | 有告警（如匹配到空的清单） | 点进「跑批历史」看明细，修数据或丢给 agent |
| 🔴 红 | 跑批失败 | 把现象贴给你的 agent，它读着 AGENTS.md 就知道怎么修 |

**③ 读表**

「管理报表」页按维度 × 指标出数，可筛选、切账套、一键导出 Excel。任何数字看不懂，
点指标名就弹出**中文口径说明**——口径不靠人脑记忆，界面随时可查。「数据血缘」页能看到
每个数字从哪张表哪列来。

**想改什么？交给 agent。**

| 你想要 | 对 agent 说 |
|---|---|
| 改口径 / 加指标 | 「改 instances/sales/metrics.yml：毛利率的算法改成……，然后重编译重跑」 |
| 加一张报表 | 「在 dashboard.yml 加一张 区域 × 毛利率 的月表」 |
| 接一个新公司 | 「读 docs/AI-操作手册.md 的 R-11 装配线体检，给投放区这批文件起草六份配置」 |

红线由系统兜着：口径唯一出处在 `metrics.yml`、报表只读 marts 层、每批过三层契约——
agent 再怎么折腾，数字不会悄悄错。完整操作配方见 [docs/AI-操作手册.md](docs/AI-操作手册.md)。

## 🔌 让你的 AI agent 连上来

明账内置 MCP 服务（stdio、只读、全程审计）。你的 agent 获得六个工具：
**指标目录**（含中文口径）、**报表查询**（只能查已声明的维度×指标——明细行在架构上就摸不到）、
**数据健康诊断**（"这期报表为什么没出？"）、**口径查询**。

<div align="center">
<img src="docs/assets/flow-agent-qa.png" width="92%" alt="agent 通过 MCP 只读问数，答案自带口径" />
<sub>agent 只读问数，只能查声明的维度 × 指标，答案自带口径——全程审计留痕。</sub>
</div>

```json
{ "mcpServers": { "clearledger": {
    "command": "C:/path/to/clearledger/.venv/Scripts/python.exe",
    "args": ["C:/path/to/clearledger/mcp_server.py"] } } }
```

偏好 HTTP？启用 `data/openapi_keys.json`（见 `openapi_keys.example.json`），带 `X-API-Key`
调用 `/api/open/*`。每次调用都有审计留痕。

## 📍 更新计划

| 版本 | 代号 | 主题 | 状态 |
|---|---|---|---|
| v0.1 | 第一桶数据 | 端到端最小闭环 | ✅ 已交付 |
| v0.2 | 看得见 | 一体化门户：血缘/红绿灯/字典/报表 | ✅ 已交付 |
| v0.3 | 通用积木 | 六配置+语义引擎+多账套+账套切换 | ✅ 已交付 |
| v0.4 | AI 装配线 | 接入体检器 + 开放 MCP + 界面中文化（中文别名层） | ✅ 已交付 |
| v0.5 | 配置工作台 | 配置工作台 + 报表分层（base 级联）+ 挂起队列覆盖匹配契约 | ✅ 已交付 |
| v0.6 | 复杂规则 | 层间勾稽护栏 → 指标阶梯 → 时间智能 → 分摊引擎 + Gantt 运行视图 | 🔨 进行中 |
| v0.7 | 多用户与权限 | 第六块积木：permissions.yml、统一门户 | ⏳ 计划中 |
| v1.0 | 正式版 | 生产加固 + AI 自审常态化 | ⏳ 计划中 |

完整叙事版（投资人向）：[docs/产品路线图-投资人版.md](docs/产品路线图-投资人版.md)

## 🤝 参与

项目还在快速成形期，欢迎 Issue 与想法。动手前请先读
[AGENTS.md](AGENTS.md)（AI-Native 工程章程）与
[AI 操作手册](docs/AI-操作手册.md)：架构、红线（口径唯一出处）、操作配方都在里面。

## 🙏 致谢 · 站在开源巨人的肩膀上

明账是开源方法的受益者，也是回馈者。本项目的地基与方法论，直接构建在这些项目之上：

**构建于（运行时依赖）**

[![DuckDB](https://img.shields.io/badge/DuckDB-8B5CF6.svg)](https://github.com/duckdb/duckdb) ⭐ 30k+
[![dbt](https://img.shields.io/badge/dbt--core-FF69B4.svg)](https://github.com/dbt-labs/dbt-core) ⭐ 10k+
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg)](https://github.com/fastapi/fastapi) ⭐ 80k+
[![ECharts](https://img.shields.io/badge/ECharts-AA344D.svg)](https://github.com/apache/echarts) ⭐ 62k+
[![AntV G6](https://img.shields.io/badge/AntV%20G6-2563EB.svg)](https://github.com/antvis/G6) ⭐ 11k+
[![SQLGlot](https://img.shields.io/badge/SQLGlot-4CAF50.svg)](https://github.com/tobymao/sqlglot) ⭐ 7k+
[![APScheduler](https://img.shields.io/badge/APScheduler-673AB7.svg)](https://github.com/agronholm/apscheduler) ⭐ 6.2k
[![pandas](https://img.shields.io/badge/pandas-150458.svg)](https://github.com/pandas-dev/pandas) ⭐ 45k+

**方法论借鉴**

[![Inspect AI](https://img.shields.io/badge/Inspect_AI(UK_AISI)-8B5CF6.svg)](https://github.com/UKGovernmentBEIS/inspect_ai) —— Task/Solver/Scorer 三段分离，启发了我们的评估架构
[![Hypothesis](https://img.shields.io/badge/Property_Based_Testing(Hypothesis)-7C3AED.svg)](https://github.com/HypothesisWorks/hypothesis) ⭐ 7.8k —— 独立 oracle + 随机生成 → 验收答案的独立生成
[![agent-testing](https://img.shields.io/badge/Agent_Red_Team_Tools-0891B2.svg)](https://github.com/topics/agent-testing) —— 对抗注入思路 → 混沌测试条款

> 一句话：**引擎是它们的，积木是配置的，装配是 AI 的。**
> 感谢以上项目的维护者与社区——明账每个版本都会同步更新这份名单。

## 📄 协议

[MIT](LICENSE) —— 随便用，随便改，拿去做生意也行。

---

<div align="center">
<sub>一个不写代码的人，和一个读所有代码的 AI，一起造的。<br>Built by a human who can't read code, together with an AI who reads everything.</sub>
</div>
