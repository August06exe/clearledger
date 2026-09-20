# AI 点火指南 —— 把明账在一台新电脑上跑起来

> **你是谁、这是什么**：你（AI agent）刚拿到一个刚克隆的明账 ClearLedger 仓库。
> 你的任务：从零把它带到「门户可访问、演示账套全绿」，然后向人类交付验收。
> 预计耗时 10–25 分钟（大头是 pip 依赖下载，视网速）。
>
> 这是**点火文档**：只在初始化和新环境引导时读。日常维护配方见
> [AI-操作手册](AI-操作手册.md)，工程章程与红线见根目录 [AGENTS.md](../AGENTS.md)。

## 0. 三十秒理解这个项目

- **明账是私有化管理报表数据底座**：Excel/CSV 投放 → 三层契约校验摄取 → dbt 管道 → 门户（红绿灯/血缘/字典/报表）。
- **多账套**：一个公司 = `instances/<账套>/` 下五份 YAML 配置 + 独立 DuckDB 库文件。内置演示账套：`sales`（销售公司）、`restaurant`（连锁餐饮）；`retail`/`hro` 是开发测试账套，**仓库不带其演示数据**，全新克隆后它们显示未跑批属预期。
- **分工**：你（agent）负责搭环境、跑批、改配置、修报错；人负责丢文件、定口径、验收结果。
- **引擎 `semantic/` 零业务预设**——一切公司相关的东西都在 YAML 配置里，改配置不改引擎。

## 1. 前置检查（动手前逐项确认）

| 项 | 检查命令 | 要求 |
|---|---|---|
| 操作系统 | — | Windows 10/11（当前主力平台；Linux/macOS 可跑但未验证） |
| Python | `py --version` 或 `python --version` | 3.11+ |
| Git | `git --version` | 任意近代版本 |
| 磁盘 | — | ≥ 2 GB（venv + DuckDB + dbt） |
| 端口 | `netstat -ano \| grep ":8620"` | 8620 空闲（被占先杀，见 §5 P-01） |

任一不满足 → 停下来向用户说明缺什么、给下载链接（python.org），不要自行下载安装系统级软件。

## 2. 自举流水线（按序执行，每步有验证点）

以下命令假设 Git Bash、仓库根目录。**每步验证通过再走下一步**。

### Step 1 虚拟环境

```bash
python -m venv .venv
.venv/Scripts/python.exe -V          # 应输出 3.11+
```

### Step 2 依赖

```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/dbt.exe --version      # 应输出 dbt-core 1.9.x
```

> 网慢可加清华镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`。
> `mcp` 依赖锁定 `>=1.2,<2`（2.x 改了 FastMCP 接口，升上去 MCP 服务会挂）。

### Step 3 演示数据（销售公司 + 连锁餐饮）

```bash
.venv/Scripts/python.exe sample_data/generate.py
.venv/Scripts/python.exe sample_data/generate_restaurant.py
```

生成物落在 `instances/<账套>/data/inbox/`（各 CSV）。此步没有报错即成功。

### Step 4 首次跑批（每个账套三步链）

```bash
for 账套 in sales restaurant; do
  .venv/Scripts/python.exe -m semantic.ingest_run   --instance $账套
  .venv/Scripts/python.exe -m semantic.compile_dbt  --instance $账套
  (cd instances/$账套/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors)
done
```

**验证点**：每个账套的 dbt build 末尾 `PASS=WARN=ERROR` 汇总里 ERROR 必须为 0；
sales 基线 37 节点、restaurant 27 节点（数量对不上说明有节点没跑，看上 方日志）。

### Step 5 系统自检

```bash
.venv/Scripts/python.exe ops/doctor.py
```

**验证点**：无 red 项（个别 warn 如「门户未运行」此时正常，下一步就启动）。

### Step 6 启动门户

```bash
(.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8620 > logs/uvicorn.log 2>&1 &)
sleep 4
curl -s http://127.0.0.1:8620/api/instance    # 应返回 JSON，current 为某账套
```

**验证点**：HTTP 200 + JSON。然后浏览器打开 `http://127.0.0.1:8620` 交给用户。

## 3. 交付验收清单（自查完再叫人）

- [ ] `ops/doctor.py` 无 red
- [ ] 门户可打开，顶栏可切换「演示销售公司 / 演示连锁餐饮」两个账套
- [ ] 总览页两账套红绿灯均为绿（或黄且有明确 warn 原因）
- [ ] 管理报表页「区域月度」等报表有数、可导出 Excel
- [ ] 血缘页蜘蛛网可渲染、节点可点

## 4. 用户接下来的三个常见诉求（引导话术）

| 用户说 | 你做 |
|---|---|
| 「换成我的真实数据」 | 读操作手册 **R-06 装配线体检**：文件投放到该账套 inbox → `python -m semantic.inspect --instance <账套>` 出配置草案 → 人审核 → 转正重跑 |
| 「让我的常驻 agent 也能查数」 | 读操作手册 **R-10 MCP 接入**：mcp_server.py 挂进 agent 客户端，或 HTTP `X-API-Key` 走 `/api/open/*` |
| 「改个口径 / 加张报表」 | 只改 `instances/<账套>/metrics.yml` 或 `dashboard.yml` → 重跑 compile_dbt + dbt build（红线：口径唯一出处） |

## 5. 首跑常见故障

| 症状 | 处置 |
|---|---|
| **P-01** 端口 8620 被占 | `for pid in $(netstat -ano \| grep ":8620" \| grep LISTENING \| awk '{print $5}' \| sort -u); do taskkill //F //PID $pid; done` |
| **P-02** pip 超时 | 换清华镜像重试；`duckdb`/`dbt-duckdb` 体积大属正常 |
| **P-03** `dbt: command not found` | venv 没装好，删 `.venv/` 从 Step 1 重来 |
| **P-04** 跑批红灯 | 看该账套 `instances/<账套>/pipeline/logs/` 与 `target/run_results.json`，按手册故障 playbook 归因 |
| **P-05** Git Bash 里出现名为 `nul` 的文件 | 重定向误用 `>nul` 所致（Windows 保留名，会让 git add 崩溃）：静默输出一律用 `>/dev/null`，已生成的 nul 文件用 `rm ./nul` 删除 |

## 6. 红线（十秒版，全文见 AGENTS.md）

1. 指标口径只存在于 `instances/<账套>/metrics.yml` 与 wide.yml 派生列，报表层与前端只引用不重算
2. 查询编译器只读 marts 层，不碰 staging/raw
3. `instances/<账套>/pipeline/models` 是生成物，禁止手改
4. `data/`、`logs/` 不入 git；动 `.duckdb` 前先跑 `备份数据.bat`
5. YAML 配置键禁用 `on/off/yes/no`（YAML 1.1 布尔坑，join 键因此叫 `keys`）

---

*本文件是 AI-Native 文档体系的一部分：AGENTS.md（章程）→ 本指南（点火）→ AI-操作手册（日常配方）→ 迭代日志（历史教训）。改了启动方式记得同步这里。*
