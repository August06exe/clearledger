# v0.5 开放接口验收测试计划（无答案版·测试 Agent 执行手册）

> 命题 Agent 出品。被测对象（黑盒）：**MCP 六工具**（`mcp_server.py`）、**HTTP 开放端点**
> （`/api/open/*` + `X-API-Key`）、**装配线体检器**（`semantic.inspect`）。
> 对外承诺出处：`docs/AI-操作手册.md` R-10 / R-11、`docs/语义层与多实例设计.md` §3.2/§4.3、
> 决策 D14 / P-08 / N-10。
> 三权分立纪律：测试 Agent **不改引擎、不改被测实现、不改本 TESTPLAN、不改 `expected/` 密封答案**；
> 只执行、按 §5 规范存档实际行为；全部数值判分由 `expected/` + `judge/score.py` 机械完成。

---

## 0. 执行环境与密封性校验（开始前必做）

```bash
cd /d/Workshop/3000-Projects/3005-DA-AI\ Native数据底座系统    # 仓库根（下文 <ROOT>）
.venv/Scripts/python.exe ops/doctor.py --json                  # 系统健康基线（overall=ok 才开工）
curl -s http://127.0.0.1:8620/api/runs/status >/dev/null && echo 门户在运行

# 密封校验（评审前可随时重跑；全 OK 才有效）
cd <ROOT>/tests/v0.5/expected && sha256sum -c manifest.sha256
# 复现性：重跑生成器后哈希必须逐字节一致（P-0）
cd <ROOT> && .venv/Scripts/python.exe tests/v0.5/generate.py
.venv/Scripts/python.exe tests/v0.5/generate.py
cd tests/v0.5/expected && sha256sum -c manifest.sha256    # 应 OK
```

**基准漂移纪律**：`expected/` 密封自生成时刻的仓库状态（metrics.yml / v0.4 answer.json /
`data/runs/history_restaurant.json` / `pipeline/target/run_results.json`）。
若你在本轮测试中**触发过跑批或改过任何 yml / inbox**，判分前必须重跑
`tests/v0.5/generate.py` 重新密封（生成器确定性，随仓库状态同步），并在报告中记录重密封原因。
禁止手工编辑 expected/ 下任何文件。

## 1. 被测面与凭据

| 面 | 入口 | 凭据/参数 |
|---|---|---|
| MCP | `import mcp_server`（stdio server，六工具：list_instances / list_metrics / list_reports / query_report / get_data_status / get_caliber） | 进程内直调，见 §2.1 |
| HTTP | `http://127.0.0.1:8620` + `/api/open/reports`、`/api/open/metrics`、`/api/open/reports/{key}/data`、`/api/open/status` | 请求头 `X-API-Key`；测试钥匙 = `data/openapi_keys.json` 现存唯一 key |
| 体检器 | `.venv/Scripts/python.exe -m semantic.inspect --instance restaurant` | 产出/刷新 `instances/restaurant/onboarding/` |

- 钥匙只此一把（principal=boss-agent，note=夜航测试钥匙）。**不得**为测试新增钥匙、不得改 `data/openapi_keys.json`。
- HTTP 端点均带可选 `?instance=` 参数（openapi.json 自证）；不带时落到当前设置账套
  （`data/settings.json` 当前=sales）。**判分相关调用一律显式带 `?instance=`**。
- 四个正式账套：sales（演示销售公司）/ restaurant（演示连锁餐饮）/ retail（荟品汇零售连锁）/ hro（睿才人力）。

## 2. 调用姿势样例（测试 Agent 直接拷用）

### 2.1 MCP（进程内直调）

```python
# -*- coding: utf-8 -*-
import sys, json, asyncio
ROOT = r"D:\Workshop\3000-Projects\3005-DA-AI Native数据底座系统"
sys.path.insert(0, ROOT)
import mcp_server  # noqa: E402

def find_server():
    """定位 mcp_server.py 里的 server 对象（具备 call_tool）。"""
    for n in ("mcp", "server", "app", "clearledger"):
        obj = getattr(mcp_server, n, None)
        if obj is not None and hasattr(obj, "call_tool"):
            return obj
    raise RuntimeError("未找到具备 call_tool 的 server 对象：查看 mcp_server.py 末尾变量名后显式指定")

SRV = find_server()

async def mcp_call(name: str, args: dict | None = None):
    """调用 MCP 工具。约定：content[0].text 为 JSON 字符串。
    返回 (ok, parsed, raw_text)；工具抛异常时 ok=False、raw_text=异常摘要。"""
    try:
        result = await SRV.call_tool(name, args or {})
        content = result[0] if isinstance(result, tuple) else result   # 兼容 (contents, extra) 两形态
        text = content[0].text if hasattr(content[0], "text") else str(content[0])
    except Exception as e:                      # noqa: BLE001 —— 错误本身也是测试证据
        return False, None, f"{type(e).__name__}: {e}"
    try:
        return True, json.loads(text), text
    except Exception:
        return True, None, text                 # 非 JSON 文本（如报错文案）原样保留

async def discover_tools():
    tools = await SRV.list_tools()
    return [{"name": t.name, "description": getattr(t, "description", ""),
             "inputSchema": getattr(t, "inputSchema", None)} for t in tools]

# 用法：
#   ok, parsed, raw = asyncio.run(mcp_call("list_instances", {}))
#   tools = asyncio.run(discover_tools())
```

> **先做 P-0 工具发现**：把 `discover_tools()` 结果存 `judge/actual/mcp_tools.json`。
> 六工具的**准确参数名**以各自 `inputSchema` 为准（下文 `filters`/`limit`/`report` 等为惯用名假设；
> 若 schema 命名不同，按 schema 适配并把实际签名记进报告，判分不受影响）。

### 2.2 HTTP（urllib + X-API-Key）

```python
# -*- coding: utf-8 -*-
import json, urllib.request, urllib.error
from urllib.parse import quote
ROOT = r"D:\Workshop\3000-Projects\3005-DA-AI Native数据底座系统"
BASE = "http://127.0.0.1:8620"
API_KEY = next(iter(json.load(open(ROOT + r"\data\openapi_keys.json", encoding="utf-8"))))

def http_get(path: str, api_key: str | None = API_KEY):
    """返回 (status, parsed_or_text)。HTTPError 也带状态码返回，不抛出。"""
    req = urllib.request.Request(BASE + path)
    if api_key is not None:
        req.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")

# 用法（筛选值拼参必须 quote）：
#   http_get("/api/open/status?instance=retail")
#   http_get("/api/open/reports/monthly_kpi/data?instance=retail&limit=5")
```

## 3. 数值 Case（N-00 ~ N-34，共 35 条）

判分全部由 `judge/score.py` 对照 `expected/` 机械完成；你的职责是**按 §5 schema 存档**。
行集判分口径：列集合一致、按维度键对齐（时间键归一 `YYYY-MM-DD*`→`YYYY-MM`）、行数一致、
逐格数值一致（金额/计数容差 0.01；比率容差 1e-6；`null` 必须精确是 null 不是 0；
比率若 actual≈expected×100 判 percent_literal 嫌疑＝失败）；一键多行记 inflation 失败；
行序只记录不判。

| Case | 调用 | 存档 → 判分依据 |
|---|---|---|
| N-00 | §2.1 `discover_tools()` | `actual/mcp_tools.json` → 六工具名齐备、各带 inputSchema |
| N-01 | MCP `list_instances` | `actual/list_instances.json` → 账套名集合与 title 逐一吻合；**不得出现下划线开头条目** |
| N-02 | MCP `list_metrics(instance='sales')` | `actual/metrics_list_sales.json` → name 集合、逐指标 expr、format |
| N-03 | MCP `list_metrics(instance='restaurant')` | `actual/metrics_list_restaurant.json` → 同上 |
| N-04 | MCP `list_metrics(instance='retail')` | `actual/metrics_list_retail.json` → 同上（13 指标） |
| N-05 | MCP `list_metrics(instance='hro')` | `actual/metrics_list_hro.json` → 同上（12 指标） |
| N-06~11 | MCP `query_report(instance='retail', report=<key>)`，key ∈ monthly_kpi / region_month / category_month / channel_month / store_rank / supplier_rank，**无筛选全量** | `actual/report_rows_retail_<key>.json` → 与密封行集投影一致 |
| N-12~17 | MCP `query_report(instance='hro', report=<key>)`，key ∈ monthly_kpi / bu_month / group_rank / customer_ar / industry_month / contract_ledger | `actual/report_rows_hro_<key>.json` → 同上 |
| N-18 | MCP `query_report(instance='retail', report='region_month', filters={'城市':'上海'})` | `actual/report_filtered_retail_region_month_cityshanghai.json` → 只剩华东（上海店）12 行（v0.4 P-6a） |
| N-19 | MCP `query_report(instance='retail', report='channel_month', filters={'渠道':'电商'})` | `actual/report_filtered_retail_channel_month_ecommerce.json` |
| N-20 | MCP `query_report(instance='hro', report='industry_month', filters={'行业':'互联网'})` | `actual/report_filtered_hro_industry_month_internet.json` |
| N-21 | MCP `get_data_status(instance='restaurant')` | `actual/status_restaurant.json` → 灯色=green、raw 文本含其最新 run_id、无 red |
| N-22 | MCP `get_data_status(instance='sales')` | `actual/status_sales.json` → 无跑批历史不谎报；灯色不得 yellow/red |
| N-23 | MCP `get_data_status(instance='retail')` | `actual/status_retail.json` → 灯色不得 green/red（其基线含 10 个 warn，黄=warn 承诺） |
| N-24 | MCP `get_data_status(instance='hro')` | `actual/status_hro.json` → 同上（4 个 warn） |
| N-25 | MCP `get_caliber` 六连：retail 毛利率 / retail 库存周转率 / hro 回款率 / hro 人均产值 / sales 收入 / restaurant 客单数 | `actual/caliber_<inst>_<metric>.json` ×6 → expr 一致、desc 非空、format 一致 |
| N-26 | MCP `list_reports(instance='retail')` | `actual/list_reports_retail.json` → key 集合、title、metrics 清单 |
| N-27 | MCP `list_reports(instance='hro')` | `actual/list_reports_hro.json` → 同上 |
| N-28 | MCP `list_reports(instance='sales')` | `actual/list_reports_sales.json` → 同上 |
| N-29 | MCP `list_reports(instance='restaurant')` | `actual/list_reports_restaurant.json` → 同上 |
| N-30 | HTTP `GET /api/open/reports?instance=retail` | `actual/http_reports_retail.json` → 报表目录与 N-26 密封一致（两种形态同源承诺） |
| N-31 | HTTP `GET /api/open/reports/monthly_kpi/data?instance=retail` | `actual/http_report_data_retail_monthly_kpi.json` → 行集与 N-06 密封一致 |
| N-32 | HTTP `GET /api/open/reports/contract_ledger/data?instance=hro` | `actual/http_report_data_hro_contract_ledger.json` → 行集与 N-17 密封一致 |
| N-33 | HTTP `GET /api/open/metrics?instance=hro` | `actual/http_metrics_hro.json` → 指标目录与 N-05 密封一致 |
| N-34 | HTTP `GET /api/open/status?instance=restaurant` | `actual/http_status_restaurant.json` → 灯色=green 且 run_id 与 N-21 一致 |

**status 判分细则（命题裁定，写死进判分器）**：有 `data/runs/history_<inst>.json` 的账套
（当前仅 restaurant），最近跑批事实（run_id/灯色）以密封值为准；无 history 的账套允许
"无跑批"类取值（none/unknown/never/gray/null/缺失字段），但**灯色不得与
`pipeline/target/run_results.json` 事实矛盾**（warn>0 报绿、全过报黄、失败报绿均违背
"黄=warn/绿=全过/红=退出码非零"承诺，记 fail）；凡报出的"缺失文件/未导入"类清单必须为空
（doctor 基线：四账套投放区齐全）。

## 4. 行为 Case（B-01 ~ B-13，共 13 条）

每条的完整断言规格（must_contain / identify_all / expect_status 等）密封在
`expected/behavior.json`——你存证据，判分器照规格断言。证据文件名以 `b<NN>_` 前缀匹配
（`b01_任意后缀.json` 均可，下表给推荐名）。

| Case | 操作 | 存档 | 判分要点 |
|---|---|---|---|
| B-01 | MCP `list_metrics(instance='_no_such_instance__')` | `actual/b01_unknown_instance.json` | 必须报错；文案能识别全部四个账套（名或 title 出现） |
| B-02 | MCP `query_report(instance='retail', report='_no_such_report__')` | `actual/b02_unknown_report.json` | 必须报错；文案含 retail 可用报表 key（密封清单） |
| B-03 | MCP `get_caliber(instance='retail', metric='_no_such_metric__')` | `actual/b03_unknown_metric.json` | 必须报错；文案含可用指标名 |
| B-04 | MCP `query_report(instance='retail', report='region_month', filters={'不存在的维度__':'任意值'})` | `actual/b04_unknown_filterdim.json` | **维度名非法必须报错**并列可用维度（P-08，region_month 声明 filters=[城市]）——不得静默变全量 |
| B-05 | MCP `query_report(instance='retail', report='region_month', filters={'大区':"华东' OR 1=1--"})` | `actual/b05_inject_mcp.json` | 不报错；行集=全量 36 行且逐值与密封一致（D14 静默回退）；响应文本不含 `OR 1=1`。行集逐值吻合即"无注入字面量进 SQL"的可观察等价断言 |
| B-06 | HTTP `GET /api/open/status?instance=retail`，**不带** X-API-Key | `actual/b06_http_nokey.json` | 状态码 ∈ {401,403} |
| B-07 | 同路径，`X-API-Key: cl-invalid-key-for-test-000` | `actual/b07_http_badkey.json` | 状态码 ∈ {401,403} |
| B-08 | HTTP `GET /api/open/reports/region_month/data?instance=retail` 追加注入参数（`filter=大区:<注入值>` 与 `大区=<注入值>` 两种都试） | `actual/b08_inject_http.json` | 200；行集=全量 36 行；body 不含 `OR 1=1`；不得 5xx。若端点实际声明了 filter 参数，用该参数注入重试并记录（观察项） |
| B-09 | ① MCP `query_report(retail, monthly_kpi, limit=100000)` ② HTTP `.../monthly_kpi/data?instance=retail&limit=5` ③ HTTP 同路径 `&limit=abc` | `actual/b09_limit.json` | ① 不报错且行数 ≤ 12（越界钳制）② **恰 5 行**（R-10 原文示例）③ 状态码不得 ∈ {500,502,503} |
| B-10 | 探测法：`mkdir instances/_probe_openapi_tmp`（内放最小 `instance.yml`：`name: _probe_openapi_tmp` + `title: 探测副本`），调 MCP `list_instances`，**测完立即删除该目录** | `actual/b10_underscore.json`（含 probe_created 标记与返回原文） | 返回不含任何下划线开头条目（R-11：下划线开头=测试副本，永不视为正式账套） |
| B-11 | 记录调 MCP 前后 `logs/mcp_audit.jsonl` 行数（`wc -l`） | `actual/b11_audit.json`（lines_before/lines_after） | 判分器直接核验该文件：存在、每行合法 JSON（JSONL）、调用后行数增长（R-10：全调用审计） |
| B-12 | MCP `get_data_status(instance='_no_such_instance__')` | `actual/b12_unknown_instance_status.json` | 必须报错；文案能识别全部四个账套 |
| B-13 | `.venv/Scripts/python.exe -m semantic.inspect --instance restaurant`（会刷新 `instances/restaurant/onboarding/`，属 R-11 预期行为） | `actual/b13_inspect_restaurant.json`（exit code + inspect_report.md 全文） | join 建议包含 **2 条既有关联**：`orders←菜品编码—dishes`、`orders←门店编码—stores`（或单行内同时出现 orders+dishes+菜品编码 / orders+stores+门店编码）；报告提及 config_draft 草案产出 |

**错误判定词表（判分器内置）**：证据 `ok=false`，或原文命中
`错误|报错|未知|不存在|未找到|不支持|invalid|unknown|not found|error`（大小写不敏感）。
若被测对象用其他措辞报错导致漏判，如实记录，留评审裁决——不要为了绿灯改证据。

## 5. 实际结果收集规范（judge/actual/）

所有文件放 `tests/v0.5/judge/actual/`（UTF-8 JSON，`ensure_ascii=False`）。

**数值 Case 两种形态**：
- MCP 报表类（N-06~20）：`{"columns": [...], "rows": [ {列: 值}, ... ]}`（即 `parsed` 的
  标准形；时间值原样存，判分器归一）。
- 其余 MCP/HTTP 类：`{"ok": true, "http_status": null, "raw": "<content[0].text 原文>",
  "parsed": <json.loads 之后原样>, "normalized": <仅当需要字段映射时>}`。
  **字段名映射规则**：若返回字段与标准名（name/expr/format/desc/key/title/dimension/metrics）
  不同，映射到标准名并把映射表写进 `"field_map"`；无法映射的字段存 `null` 并在报告说明。

**行为 Case 证据**统一信封：`{"tool_or_endpoint": "...", "args_or_path": {...},
"ok": <调用是否成功返回>, "raw": "<原文/响应体全文>", "parsed": <可为 null>,
"http_status": <HTTP 时必填>}`。B-10/B-11/B-13 按各自表格内的附加键。

**收集顺序建议**：P-0 工具发现 → N-01~N-05 / N-26~N-29（目录类）→ N-06~N-20（报表类）
→ N-21~N-25 → N-30~N-34（HTTP 面）→ B-01~B-12 → B-13（体检器，会写 onboarding/，放最后）
→ 跑 `judge/score.py`。

## 6. 判分

```bash
cd <ROOT>
.venv/Scripts/python.exe tests/v0.5/judge/score.py                 # 默认 --tag round1
.venv/Scripts/python.exe tests/v0.5/judge/score.py --tag round2    # 分轮落盘 score_<tag>.json
.venv/Scripts/python.exe tests/v0.5/judge/score.py --actual-dir <目录>   # 默认 judge/actual/
.venv/Scripts/python.exe tests/v0.5/judge/score.py --strict-manifest  # expected/ 漂移即硬失败
```

- 判分器只读 `expected/` + `judge/actual/` + `logs/mcp_audit.jsonl`，不读引擎代码与你的报告判定。
- 输出 `tests/v0.5/judge/score_<tag>.json` + stdout 摘要（每 Case PASS/FAIL/NOT_RUN、失败明细前 12 条）。
- 证据文件缺失 → 该 Case 记 NOT_RUN 并计入总失败（不许静默缩表）。
- `expected/` 与 manifest 不符 → 摘要顶部显著警告（`--strict-manifest` 时直接 fail）。
- 同一 tag 重跑覆盖旧结果文件，天然幂等。

## 7. 交付与红线

- 交付 `tests/v0.5/report_v0.5.md`：每 Case 一条记录（实际值/证据摘要/判定）；
  "预期 vs 实际"不符处**不擅自归因**，留评审 Agent 裁决；引擎能力缺口单独汇总。
- 与 v0.4 相同的三权分立红线：不改引擎与被测实现、不改密封答案、不绕过测试让绿灯变绿。
- B-13 会刷新 `instances/restaurant/onboarding/`（R-11 正常产物）；测完 `git status` 若有
  该目录变更，在报告注明（是否还原交评审定夺）。
