# v0.4 语义引擎极限验收测试计划（无答案版·测试 Agent 执行手册）

> 命题 Agent 出品。本文件只写**命令与行为断言**：不出现任何指标数值——
> 全部数值判分由 `S1_retail/expected/answer.json` 与 `S2_hro/expected/answer.json`
> 机械完成（行集、行序、逐格数值）。场景事实、契约、混沌条款的唯一权威是各自 SPEC：
> `S1_retail/SPEC.md`、`S2_hro/SPEC.md`。
> 三权分立纪律：测试 Agent **不改引擎、不改生成器、不改 SPEC、不改密封答案**；
> 只执行、记录实际行为、标注"实际 vs 预期类别"是否一致；实现细节一律以黑盒观察为准。

---

## 0. 执行环境与密封性校验（开始前必做）

```bash
cd /d/Workshop/3000-Projects/3005-DA-AI\ Native数据底座系统    # 仓库根（下文简写 <ROOT>）
.venv/Scripts/python.exe ops/doctor.py --json                  # 系统健康基线
```

密封校验（评审前可随时重跑）：

```bash
cd <ROOT>/tests/v0.4/S1_retail/expected && sha256sum -c manifest.sha256
cd <ROOT>/tests/v0.4/S2_hro/expected  && sha256sum -c manifest.sha256
# 复现性：重跑生成器后哈希必须不变
cd <ROOT> && .venv/Scripts/python.exe tests/v0.4/S1_retail/generate.py
.venv/Scripts/python.exe tests/v0.4/S2_hro/generate.py
cd tests/v0.4/S1_retail/expected && sha256sum -c manifest.sha256   # 应 OK
cd ../../S2_hro/expected  && sha256sum -c manifest.sha256          # 应 OK
```

- **行为断言 P-0**：两次生成，`answer.json` 的 SHA256 逐字节一致（固定 seed 复现性）。

## 1. 装配（两实例同构，<name> ∈ {retail, hro}）

### 1.1 生成 inbox 数据

```bash
.venv/Scripts/python.exe tests/v0.4/S1_retail/generate.py   # → instances/retail/data/inbox/
.venv/Scripts/python.exe tests/v0.4/S2_hro/generate.py      # → instances/hro/data/inbox/
```

- **P-1**：生成器退出码 0；打印的混沌注入统计与各自 SPEC §7.1 的行数逐项一致
  （S1：A1=25/A2=15/A3=40/A4=30/A5=3/A6=12/A7=5/A8=1/A9=2；S2：H1=8/H2=2/H3=5/H4=2/H5=6/H6=8/H7a=30/H7b=12/H10=1）。
- **P-2**：S1 inbox 10 个文件（含诱饵 `采购单_202606.csv`）、S2 inbox 9 个文件（含诱饵
  `回款记录_202607.csv`）；诱饵文件 mtime 早于正式文件（`ls --time-style=full-iso` 验证）。
- **P-3**：流水级行数 ≥ 10 万/实例（生成器打印的台账行数即权威）。

### 1.2 写五配置 + instance.yml

按各 SPEC **附录 A** 的基线 YAML 逐字写入 `instances/<name>/{instance.yml,sources.yml,wide.yml,dimensions.yml,metrics.yml,dashboard.yml}`。
（语义内容必须与基线一致；注释格式可自定。）

### 1.3 全链路命令

> 命令形态以引擎实际 CLI 为准（下为设计文档/操作手册形态）；若不同，记录实际形态后等价执行。

```bash
# ① 摄取 + 契约校验（red → 退出非零）
.venv/Scripts/python.exe -m semantic.ingest_run  --instance retail
.venv/Scripts/python.exe -m semantic.ingest_run  --instance hro
# ② 编译（配置 → dbt project，生成物进 instances/<name>/pipeline/）
.venv/Scripts/python.exe -m semantic.compile_dbt --instance retail
.venv/Scripts/python.exe -m semantic.compile_dbt --instance hro
# ③ 跑批（dbt build）
cd instances/retail/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --target retail --no-use-colors; cd <ROOT>
cd instances/hro/pipeline   && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --target hro    --no-use-colors; cd <ROOT>
```

**P-4（基线灯色）**：两实例全链路退出码全 0，dbt build **无 error**，只有下表黄灯/warn
（全部是 SPEC 预先声明的基线，属预期行为，不是缺陷）：

| 实例 | 预期黄灯/warn | 对应条款 |
|---|---|---|
| retail | 商品 join 匹空清单含 `P9001`、`P9002`；供应商 join 匹空清单含空键与 `SUP-9999`；销售流水渠道越枚举（门店自提）12 行；数量=0 越 range 5 行；期末数量 −10 越 range 1 行；促销折扣力度越 range 2 行；供应商结算方式越枚举（季结90）1 行；单价文本化（千分位/货币符号）转换失败 15 行（低于 0.5% 阈值）；采购单 multi_match（202606 旧文件留痕） | A1~A11 |
| hro | 合同 join 匹空清单含 `HT-9999`、`HT-8888`；交付组 join 匹空清单含空键（账单/回款行基线）；账单金额千分位 6 行；行业越枚举（文体）、级别越枚举（S级）；回款 −500 越 range 1 行；回款 multi_match（202607 旧文件留痕） | H3~H11 |

- **P-5**：`raw.contract_report`（或等价留痕）能看到上述逐项明细，且能定位到源名与列名。

## 2. 报表核对（数值判分 + 行为断言）

查询命令（形态以引擎实际为准）：

```bash
.venv/Scripts/python.exe -m semantic.query retail <报表key> [--filter 维度=值]
.venv/Scripts/python.exe -m semantic.query hro    <报表key> [--filter 维度=值]
```

**判分方法（机械）**：每张报表做一次无 filter 全量查询，与 `expected/answer.json` 同
report_key 比对：columns 集合一致、行数一致、行序一致（时间升序、维度值升序、NULL 组最后）、
每格数值一致（金额容差 ≤ 0.01 元；比率容差 ≤ 1e-4；引擎输出若为百分比字面量如 30.73，
需先除以 100 归一再比；`null` 必须精确是 null 不是 0）。可用一段临时 pandas 脚本完成，
**脚本不属于交付物**。

### 2.1 retail 六张报表

| 报表 key | 行为断言（全部必须满足） |
|---|---|
| monthly_kpi | 12 行、按月升序；每月库存周转率/毛利率非空 |
| region_month | 36 行（3 大区×12 月，大区无空值）；无时间维度缺失月 |
| category_month | 48 行；存在 `品类=null` 的组且**只在 12 个月全都出现**；该组销售额>0、毛利为 null（幽灵商品无成本） |
| channel_month | 48 行；存在 `渠道=门店自提` 组（销售额>0）；存在 `渠道=null` 组（销售额=0.0、电商销售占比=null） |
| store_rank | 8 行；不含"北京朝阳店（筹备）" |
| supplier_rank | 13 行；存在 `供应商=null` 组且其采购额>0（幽灵供应商三行之和） |

filter 行为（P-08/D14/§4.3）：

```bash
... query retail region_month --filter 城市=上海      # P-6a：只剩华东（上海店）行，月数不变
... query retail region_month --filter 城市=火星市     # P-6b：静默回退 = 全量 36 行（D14）
... query retail region_month --filter 不存在的维度=任意值   # P-6c：维度名非法必须报错并列出可用维度
... query retail store_rank  --filter 大区=华北 --filter 城市=厦门   # P-6d：组合 filter 空结果合法（华北≠厦门）
```

### 2.2 hro 六张报表

| 报表 key | 行为断言 |
|---|---|
| monthly_kpi | 12 行、按月升序；毛利率/回款率非空 |
| bu_month | 42 行；`事业部=null` 组**只出现在 6 个指定月份**（SPEC §6 行集表）；该组服务费收入=0.0、毛利率=null |
| group_rank | 7 行；`交付组=null` 行人力成本=0.0、人均人力成本=null、外派人数=0 |
| customer_ar | 25 行；`客户=null` 行回款额>0 且应收余额<0（幽灵回款） |
| industry_month | 66 行；存在 `行业=文体` 组（12 个月都有，服务费收入>0）；`行业=null` 组只在 6 个指定月份 |
| contract_ledger | 40 行；**不含**未来合同（合同.xlsx 中开始月在 2026-10 之后的合同号）；包含 `HT-9999`（外派人数=5）与 `HT-8888`（回款>0、应收<0） |

filter 行为：

```bash
... query hro bu_month --filter 行业=文体             # P-7a：只剩文体客户挂的行
... query hro customer_ar --filter 客户级别=S级        # P-7b：只剩越枚举客户所在行（黄灯值可作筛选值）
... query hro industry_month --filter 客户级别=Z级     # P-7c：静默回退全量（D14）
... query hro group_rank --filter 事业部=不存在的维度   # P-7d：维度名非法报错
```

## 3. 混沌执行清单（副本实例注入，禁止污染基线）

通用做法：

```bash
cp -r instances/retail instances/_c_retail
# 改 instances/_c_retail/instance.yml：name: _c_retail；database 指向新库文件（如 ../../../data/warehouse/_c_retail.duckdb）
# 注入 → 重跑 §1.3 全链路（ingest/compile/build）→ 记录
```

每个案例记录：{注入内容, 命令, 退出码, 灯色, 证据（日志/清单关键行）, 预期类别, 是否一致}。

### 3.1 retail 混沌案例（预期类别均引自设计 §7 与 v0.3 定谳）

| # | 注入/操作 | 跑什么 | 预期行为类别 |
|---|---|---|---|
| R1 | 门店.xlsx 复制 HD01 一行（改门店名称制造"同键不同名"） | 全链路 | fanout red → dbt error 测试 FAIL，build 退出非零；宽表膨胀被拦 |
| R2 | 销售流水 2 行改成相同流水号 | ingest + build | unique 恒 red 双层：ingest red 退出非零；若放行到 dbt 则 error FAIL（§7.2） |
| R3 | 商品.xlsx 表头 `品类`→`类别` | ingest | header_changed red，退出非零，报错指名 sources 与缺失列 |
| R4 | 库存快照清成 0 行（仅表头/0 字节） | ingest | empty_file（或 empty_after_clean）red |
| R5a | 删除 销售流水_202608.csv | ingest | file_missing red，报错能定位到 sales_flow 源 |
| R5b | 改名 `销售明细202608_最终版.csv`（两 pattern 全不命中） | ingest | 同上 red |
| R6 | metrics.yml 加 `{name: 退款额, expr: "sum(refund_amount)"}` | compile | ConfigError，报错指名悬空列 refund_amount（P-07） |
| R7 | dashboard monthly_kpi 的 metrics 加 `净利润`；category_month 的 filters 加 `渠道` | compile | ConfigError，指名未知指标/维度 |
| R8 | 查询：维度名非法 / 值非法 / 注入串 `华东' OR 1=1--` | query | 名非法报错；值非法静默回退；SQL 与结果不含注入字面量（D14/§4.3） |
| R9 | 在销售流水追加 450 行文本化单价（同 A2 两种格式，总量破 0.5%） | ingest | type_coerce_ratio 破阈值 → 黄灯升档留痕，退出码仍 0 |
| R10 | `touch 采购单_202606.csv`（旧文件变最新） | ingest | multi_match 胜出者切换为 202606（N-01"最新者胜"的对称验证），数据量变化可见 |
| R11 | 观察筹备门店：`query retail store_rank --filter 城市=北京` | query | 返回北京在营门店行；筹备店无行；记录白名单是否含无流水门店（行为观察点，不判分） |

### 3.2 hro 混沌案例

| # | 注入/操作 | 跑什么 | 预期行为类别 |
|---|---|---|---|
| H1 | 交付组.xlsx 复制 GR-F01 一行 | 全链路 | fanout red，build 退出非零 |
| H2 | 合同.xlsx 2 行改成相同合同号 | ingest + build | unique 恒 red 双层 |
| H3 | 客户.xlsx 表头 `行业`→`所属行业` | ingest | header_changed red |
| H4 | 事业部.xlsx 清空 | ingest | empty_file red |
| H5a | 删除 月度账单_202608.csv | ingest | file_missing red |
| H5b | 改名 `账单final0808.csv` | ingest | red |
| H6 | metrics.yml 加 `{name: 人效, expr: "sum(bill_x)"}` | compile | ConfigError 指名 bill_x |
| H7 | 查询三连（名非法/值非法/注入串） | query | 同 R8 |
| H8 | 在月度账单追加 4 行千分位（bills 源破 0.5%） | ingest | 黄灯升档留痕，退出 0 |
| H9 | 观察超止月账单（基线已含 H1 的 8 行） | ingest + 查 contract_ledger | **行为观察点**：引擎无跨源业务规则能力，预期正常入账、无黄灯——如实记录引擎是否给出任何提示（能力缺口证据，供评审） |
| H10 | 观察 join 链：wide 是否成功经 contracts→customers 拿到行业/级别 | compile + build | 若编译报"左列不存在"，即引擎不支持 join-on-joined-column——如实记录为引擎能力缺口（SPEC S2 §10.5），不算测试失败 |

### 3.3 恢复

全部混沌案例跑完后删除 `_c_*` 实例目录与其库文件；重跑一次基线实例链路确认全绿。

## 4. 记录与交付

- 每个 P-/R-/H- 案例一条记录（建议直接写 `tests/v0.4/report_v0.4.md`）。
- 数值判分结果：每张报表 `一致 / 不一致（差异清单前 5 条）`。
- "预期类别 vs 实际"不一致处**不要擅自归因**——写清现象，留给评审 Agent 裁决。
- 引擎能力缺口候选（join 链、超止月提示、NULL 组展示策略）单独汇总一节。


---

## 5. 轮4 加深混沌（第二轮命题：比 §3 B 类更刁钻的变体）

### 5.0 模式与命令

加深用例分三类：**red 破坏**（副本注入、答案不变）、**零漂移注入**（合法入库但答案逐字节不变——可机械验证"引擎清洗语义正确"）、**密封类注入**（合法入库且改变组结构/合计——答案按注入后口径**重密封**）。
red 与零漂移之外的注入由生成器 `--deep` 模式内置（改写 inbox 与答案同步密封，消除手工对账变量）：

```bash
# 轮4 加深口径：inbox 注入加深混沌，expected/answer.json 同步重密封
.venv/Scripts/python.exe tests/v0.4/S1_retail/generate.py --deep
.venv/Scripts/python.exe tests/v0.4/S2_hro/generate.py --deep
# 基线口径（轮2/3 判分基准；轮4 跑完切回即重跑无参命令）
.venv/Scripts/python.exe tests/v0.4/S1_retail/generate.py
.venv/Scripts/python.exe tests/v0.4/S2_hro/generate.py
```

- 两模式各自确定可复现；deep 模式 rng 链下移，未注入的随机点（如 A8 注入位置）可能与基线不同——answer 与 inbox 始终同步密封，判分不受影响。
- 本轮新密封（--deep 口径）：S1 `29ae30d4…`、S2 `69ab610f…`（完整值见 §5.4）；基线留档：S1 `65d75c7b…`、S2 `97c4b33e…`。

### 5.1 retail 加深用例（D-R4，8 条）

| # | 注入操作（文件/列/行） | 跑什么 | 引擎应表现（设计条款锚点） | 答案影响 |
|---|---|---|---|---|
| D-R4-1 | 表头同义改名：采购单_202608.csv 列 `采购单价`→`采购单价(元)` | ingest | header_changed **red**、退出码非零（§3.1 缺声明中文列→停批，防静默错列） | 无（副本注入） |
| D-R4-2 | UTF-8 BOM 双重包裹：销售流水_202608.csv 字节头写两个 `EF BB BF` | ingest | utf-8-sig 只剥一层 → 第二个 BOM（U+FEFF）并入首列表名 `流水号` → header_changed **red**；**若绿灯即引擎缺陷**（静默错列） | 无（副本注入） |
| D-R4-3 | 行尾 CRLF/LF 混用：采购退货_202608.csv 逐行交替 CRLF/LF 重写 | 全链路 | CSV 解析语义无影响 → 绿、黄灯不增；副本 marts 与基线 answer.json **逐格一致**（零漂移对账） | 无（零漂移） |
| D-R4-4 | 日期格式变异：销售流水 2 行 `销售日期` 改 `2026/09/01` 斜杠样式 | ingest | **设计未定义——考察点**。承诺行为：type: date 可解析则按语义入库、不可解析则 type_coerce yellow 计数且行去向可追溯；引擎实际解析宽严如实记录 | 不密封（双态观察） |
| D-R4-5 | 数量小数化：销售流水 3 行 `数量` 改文本 `3.0` | ingest | type: integer 双态：宽松解析（3.0→3）或 type_coerce yellow——**设计未定义，如实记录**；行不得无痕消失（v0.3 T3 底线） | 不密封（双态观察） |
| D-R4-6 | ENUM 两连：(a) 12 行（每月 1 行）`渠道` 改尾随空格（`"门店 "`/`"电商 "`）；(b) 每月 1 行 `渠道`→繁体 `"門店"`（共 12 行） | 全链路 | (a) strip_strings 先于契约（§4.1）→ 合法、无黄灯、组归属不变；(b) enum yellow、行保留（§7.1）→ 渠道月报**新增"門店"组**（每月 1 行、销售额>0） | (a) 零漂移；(b) **答案变（重密封）** |
| D-R4-7 | 折扣率=1.0 边界：5 行 `折扣率`→`1.0`（2025-09/11/12、2026-01/03） | ingest + 报表 | range [0,1] **含边界 → 通过、无 range 黄灯**；收入=0、毛利=−成本（报表可见）；"负毛利自动留痕"超出引擎契约能力（无业务规则层）——**如实记录为设计承诺边界，不算缺陷** | **答案变（重密封）** |
| D-R4-8 | 空字符串 vs NULL：6 行 `渠道` 清空为 CSV 空字段（2025-10/12、2026-01/03/05/07 各 1） | ingest + 报表 | 命题裁决：CSV 空字段=缺失，缺失≠enum 违规 → 空值入 **NULL 渠道组**并承接真实销售额（>0）；若引擎判 enum yellow 或以空串成组 → 如实记录实际行为偏离 | **答案变（重密封）** |

`--deep` 内置注入 = D-R4-6(a)(b) + D-R4-7 + D-R4-8；行集变化：channel_month **48→60**（+門店组 12 行）。

### 5.2 hro 加深用例（D-H4，8 条）

| # | 注入操作（文件/列/行） | 跑什么 | 引擎应表现（设计条款锚点） | 答案影响 |
|---|---|---|---|---|
| D-H4-1 | 表头同义改名：月度账单_202608.csv `账单金额`→`账单金额(元)` | ingest | header_changed **red** | 无（副本注入） |
| D-H4-2 | UTF-8 BOM 双重包裹：月度账单_202608.csv 双 BOM | ingest | 同 D-R4-2 → **red**；绿灯=缺陷 | 无（副本注入） |
| D-H4-3 | 行尾 CRLF/LF 混用：回款记录_202608.csv 交替行尾重写 | 全链路 | 零漂移对账（同 D-R4-3） | 无（零漂移） |
| D-H4-4 | 日期变异：账单 2 行 `月份` 改 `2026/9/1` | ingest | 同 D-R4-4，观察点 | 不密封（双态观察） |
| D-H4-5 | 金额小数文本：3 行 `账单金额` 改 `"…​.0"` 文本（不同月份） | ingest + 报表 | `"123456.0"` 为**合法 decimal 文本**→ 必然解析成功、金额同值 → 零漂移；若引擎报 type_coerce → 如实记录 | 零漂移（--deep 注入，密封值不变） |
| D-H4-6 | ENUM 两连：(a) 客户.xlsx CUST-03 `行业`→`"金融 "`；(b) CUST-07 `行业`→`金融业` | 全链路 | (a) trim 合法、无黄灯、组不变；(b) enum yellow、行保留 → 行业月报**新增"金融业"组**（12 个月，=CUST-07 全部账单挪组） | (a) 零漂移；(b) **答案变（重密封）** |
| D-H4-7 | 月服务费下界：合同.xlsx HT-0001 `月服务费`→`1000.0`（range [1000,100000] 含边界） | ingest | 通过、无黄灯；费率不进任何派生列 → 零漂移 | 无（零漂移，--deep 注入） |
| D-H4-8 | required 空值：回款记录 2 行 `合同号` 清空（不同月份，避开 HT-8888/负回款行） | ingest + 报表 | 设计 §4.2 "required 过滤"：行不进 staging/宽表；ingest 契约留痕 yellow、退出码 0（v0.3 T5 先例）→ 回款额按**剔除口径** | **答案变（重密封）** |

`--deep` 内置注入 = D-H4-5 + D-H4-6(a)(b) + D-H4-7 + D-H4-8；行集变化：industry_month **66→78**（+金融业组 12 行）。

### 5.3 轮4 密封与判分

- `--deep` 模式下 `expected/answer.json` + `manifest.sha256` 即注入后口径的密封答案，score.py 照常机械判分；red/双态用例（D-R4-1/2/4/5、D-H4-1/2/4）在**副本实例**上执行，基线 answer 不受影响。
- 本轮密封哈希：S1 `2d66c921…`（完整值见 tests/v0.4/S1_retail/expected/manifest.sha256）、S2 `69ab610fdfe85ef9…`（同 S2 manifest）；基线留档 S1 `65d75c7b…`、S2 `97c4b33e…`。
- **能力缺口观察点汇总（如实记录，不迁就）**：负毛利业务规则留痕（D-R4-7）、空值 enum 语义与空串成组（D-R4-8）、日期格式解析宽严（D-R4-4/D-H4-4）、integer 小数转换（D-R4-5）、BOM 双层剥离（D-R4-2/D-H4-2）。
