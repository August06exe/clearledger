<div align="center">

<img src="docs/assets/logo_B.png" width="72" alt="ClearLedger logo" />

# ClearLedger · 明账

**Every number, traceable to its source. · 每个数字，表里如一。**

An AI-Native reporting data platform — turn messy Excel/CSV drops into governed,
lineage-tracked management reports, assembled almost entirely from configuration.

[![License: MIT](https://img.shields.io/badge/License-MIT-2563EB.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Early_Access-F59E0B.svg)](#-roadmap)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](https://python.org)
[![Engine](https://img.shields.io/badge/Engine-DuckDB%20%2B%20dbt-8B5CF6.svg)](#-architecture)
[![MCP](https://img.shields.io/badge/MCP-Read_Only-0D9488.svg)](#-connect-your-ai-agent)
[![Docs](https://img.shields.io/badge/%E6%96%87%E6%A1%A3-%E4%B8%AD%E6%96%87-DC2626.svg)](README.zh-CN.md)

English · [中文](README.zh-CN.md)

<img src="docs/assets/hero-banner.png" width="100%" alt="ClearLedger — from messy spreadsheets to governed dashboards" />

</div>

---

> [!NOTE]
> **This is a working early-access build (开发中 · 抢鲜体验).** It already runs four live company
> instances (sales / F&B chain / retail / HRO) with red-yellow-green data governance.
> See the [Roadmap](#-roadmap) for what's landed and what's next.

## 📸 What it looks like

| Overview | Lineage graph |
|---|---|
| ![Overview](docs/assets/screenshot-overview.png) | ![Lineage](docs/assets/screenshot-lineage.png) |

| Reports | Metric caliber popup |
|---|---|
| ![Reports](docs/assets/screenshot-reports.png) | ![Caliber](docs/assets/screenshot-caliber.png) |

## 🎯 Who this is for

**Not for big companies** — they have BI teams and mature reporting pipelines. ClearLedger is for
the people who **can't wait for a sprint slot**:

- 🧭 **The BP / lead of a new project** — the board wants a dashboard *this month*, engineering says "see you in a year"
- 🏭 **Companies & departments that never digitized** — data scattered across a dozen Excel files, relayed by hand for years
- ⚡ **Department-level, ad-hoc needs** — too small for a proper project, yet it bites you every single day

**The author's story**: a new project needed reporting. Engineering's backlog put it a full year out.
Waiting was not an option — so a **BP who can't read code**, together with one AI, stood up the entire
pipeline: ingest → clean → caliber → reports → lineage. And then made it modular on purpose:
**next project? swap six config files and go.**

That's the pitch:

> **When engineering capacity can't save you, one person is a data team.**

No SQL required. No project approval queue. No ops to babysit: your AI assistant reads every config,
fixes what breaks — you only decide what the numbers *should mean*.

## ✨ Understand it in three minutes

<img src="docs/assets/promo-card1.png" width="100%" alt="Feature 1: drop files in, the pipeline does the rest (CN)" />

<img src="docs/assets/promo-card2.png" width="100%" alt="Feature 2: new company = six config blocks (CN)" />

<img src="docs/assets/promo-card3.png" width="100%" alt="Feature 3: every number introduces itself (CN)" />

## ⚙️ Architecture

```mermaid
flowchart LR
    A["📥 Excel / CSV inbox<br/>(per-instance drop zone)"] -->|"ingest<br/>+ field contracts"| B[("🦆 DuckDB<br/>raw · one file per company")]
    B -->|"compile<br/>(configs → dbt project)"| C["🔧 dbt pipeline<br/>staging → intermediate → marts"]
    C --> D["📊 Semantic layer<br/>metrics.yml = single source of caliber"]
    D --> E["🖥 Unified portal<br/>reports · lineage · dictionary · traffic lights"]
    F["🧩 SIX config blocks<br/>sources · wide · dimensions · metrics · dashboard · permissions"] -.->|drive| A
    F -.->|drive| C
    F -.->|drive| D
    F -.->|drive| E
    G["🤖 AI assembly line<br/>reads files → drafts configs → human reviews"] -.-> F
    H["🔌 MCP server<br/>(read-only, audited)"] --> E
```

The engine (`semantic/`) contains **zero business logic**. Everything company-specific lives in
**six config blocks** per instance — the engine is generic, the assembly is done by AI.

## 🧱 The six building blocks

| Block | File | What it controls |
|---|---|---|
| ① Sources | `sources.yml` | File discovery patterns, cleaning pipeline, field contracts (type / range / enum / missing policy), problem severity levels |
| ② Wide table | `wide.yml` | Declarative joins (ordered left-joins with match contracts: fanout / null-match / orphan) + derived columns |
| ③ Dimensions | `dimensions.yml` | Which columns become sliceable dimensions (drill-down, filters, grouping — zero presets) |
| ④ Metrics | `metrics.yml` | The single source of caliber: each metric = one formula + one Chinese/English description shown in the UI |
| ⑤ Dashboard | `dashboard.yml` | Reports = dimension × metrics × filters × chart type |
| ⑥ Permissions | `permissions.yml` | *(planned v0.7)* Row/column-level access, unified principal for humans and API keys |

**Three data contracts** run on every batch: entry档案 (file-name patterns that survive monthly renames,
ordered cleaning primitives, severity per problem class), field contracts (validated on ingest, violations
logged to `raw.contract_report`), and match contracts (fan-out → red test, null-match → warn + list).

Swap company = swap configs. The engine's `git diff` must be zero — that's the acceptance gate.

## 🚀 Quick start

```bash
git clone https://github.com/August06exe/clearledger.git
cd clearledger
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # Windows
# or: python -m venv .venv && .venv/bin/python -m pip install -r requirements.txt # Linux/macOS

# generate demo data for two live instances (retail & F&B chain) and run the full pipeline
.venv/Scripts/python sample_data/generate.py
.venv/Scripts/python sample_data/generate_restaurant.py
.venv/Scripts/python -m semantic.ingest_run  --instance sales
.venv/Scripts/python -m semantic.compile_dbt --instance sales
cd instances/sales/pipeline && ../../.venv/Scripts/dbt.exe build --profiles-dir . && cd ../../..

# start the portal
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8620
# open http://127.0.0.1:8620
```

> On Windows, double-click **`启动明账.bat`** — it does all of the above and opens your browser.

## 🔌 Connect your AI agent

ClearLedger ships an MCP server (stdio, read-only, fully audited). Four tools your agent gets:
**metric catalog** (with human-readable caliber), **report query** (declared dimensions × metrics only —
row-level data is architecturally unreachable), **data health diagnosis** ("what's missing this period?"),
and **caliber lookup**.

```json
{ "mcpServers": { "clearledger": {
    "command": "C:/path/to/clearledger/.venv/Scripts/python.exe",
    "args": ["C:/path/to/clearledger/mcp_server.py"] } } }
```

Prefer plain HTTP? Enable `data/openapi_keys.json` (see `openapi_keys.example.json`) and call
`/api/open/*` with an `X-API-Key` header. Every call is audit-logged.

## 📍 Roadmap

| Version | Codename | Theme | Status |
|---|---|---|---|
| v0.1 | First bucket | End-to-end minimal loop | ✅ shipped |
| v0.2 | Visible | Unified portal: lineage / traffic lights / dictionary / reports | ✅ shipped |
| v0.3 | Generic blocks | Six configs + semantic engine + multi-instance + account switching | ✅ shipped |
| v0.4 | AI assembly line | Onboarding inspector + open MCP + **UI localization (Chinese aliases for lineage/fields/status)** | 🔨 in progress |
| v0.5 | Config workbench | Visual management & editing for configs and contracts | ⏳ planned |
| v0.6 | Complex rules | Allocation / restatement / reconciliation engines | ⏳ planned |
| v0.7 | Multi-user & permissions | Sixth block: permissions.yml, unified portal (hide-only ACL) | ⏳ planned |
| v1.0 | GA | Production hardening + always-on AI self-audit | ⏳ planned |

Full narrative roadmap (investor edition, CN): [docs/产品路线图-投资人版.md](docs/产品路线图-投资人版.md)

## 🤝 Contributing

Early days — the codebase is being shaped fast. Issues and ideas are welcome; please read
[AGENTS.md](AGENTS.md) (our AI-Native engineering charter) and the
[AI operations manual](docs/AI-操作手册.md) first: they explain the architecture, the red lines
(single-source caliber), and the operational recipes.


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

[![Inspect AI](https://img.shields.io/badge/Inspect_AI(UK_AISI)-8B5CF6.svg)](https://github.com/UKGovernmentBEIS/inspect_ai) —— the Task/Solver/Scorer separation inspired our evaluation architecture
[![Hypothesis](https://img.shields.io/badge/Property_Based_Testing(Hypothesis)-7C3AED.svg)](https://github.com/HypothesisWorks/hypothesis) ⭐ 7.8k —— independent oracle + generative inputs → our acceptance-answer generation
[![agent-testing](https://img.shields.io/badge/Agent_Red_Team_Tools-0891B2.svg)](https://github.com/topics/agent-testing) —— 对抗注入思路 → 混沌条款

> One line: **the engines are theirs, the blocks are config, the assembly is AI's.**
> 感谢以上项目的维护者与社区——明账每个版本都会同步更新这份名单。


## 📄 License

[MIT](LICENSE) — use it, fork it, build your business on it.

---

<div align="center">
<sub>Built by a human who can't read code, with an AI who reads everything. · 一个不写代码的人，和一个读所有代码的 AI。</sub>
</div>
