# S1 场景圣经：荟品汇零售连锁（零售连锁进销存）

> 命题 Agent 出品（三权分立·命题方）。本文档是 S1 场景的**唯一权威**：
> 业务事实、字段契约、匹配契约、指标口径、报表定义、混沌条款、密封答案规则均以此为准。
> 测试 Agent 据此装配实例 `instances/retail/` 并执行 `../TESTPLAN.md`；
> 评审 Agent 据此对照 `expected/answer.json` 独立裁判。
> 引擎能力边界一律锚定 `docs/history/语义层与多实例设计.md`（下称"设计"）；
> 凡引擎声明能力之外的诉求，本文显式声明简化口径，不构成扣分项。

---

## 0. 一句话场景

荟品汇零售连锁是一家跨 3 大区、8 家在营门店的社区零售企业，经营食品、百货、日化三大品类。
公司按月回收四类事实数据（销售流水、采购单、采购退货、月末库存快照）与四类档案
（门店、商品、供应商、促销活动），需要一套**进销存管理报表**：卖了多少、赚了多少、
进了多少、退了多少、还压了多少货、货转得快不快、电商占多少。

---

## 1. 组织与主数据（完整虚构，生成器硬编码，禁止改动）

### 1.1 组织

总部 — 3 大区 — 8 家在营门店 + 1 家筹备门店：

| 门店编码 | 门店名称 | 城市 | 大区 | 备注 |
|---|---|---|---|---|
| HD01 | 上海人民广场店 | 上海 | 华东 | 旗舰，客流权重最高 |
| HD02 | 杭州西湖店 | 杭州 | 华东 | |
| HD03 | 南京新街口店 | 南京 | 华东 | |
| HB01 | 北京国贸店 | 北京 | 华北 | |
| HB02 | 天津滨江道店 | 天津 | 华北 | |
| HB03 | 北京朝阳店（筹备） | 北京 | 华北 | **2026-10-01 开业，全程零流水** |
| HN01 | 广州天河店 | 广州 | 华南 | |
| HN02 | 深圳福田店 | 深圳 | 华南 | |
| HN03 | 厦门中山路店 | 厦门 | 华南 | 客流权重最低 |

- 大区枚举 = [华东, 华北, 华南]；城市 8 个（每店一城，北京两店）。
- **HB03 是混沌条款 A13**：只进门店档案、不进任何流水——它不得出现在任何报表分组里，
  并作为筛选值白名单行为的观察点（见 TESTPLAN §2.1 store_rank 与 R11）。

### 1.2 商品（120 个）

| 品类 | 编码段 | 数量 | 标准成本区间（元） | 说明 |
|---|---|---|---|---|
| 食品 | FP001~FP050 | 50 | 3.00 ~ 30.00 | 单位：袋/瓶/盒 |
| 百货 | GG001~GG040 | 40 | 15.00 ~ 120.00 | 单位：个/套 |
| 日化 | RC001~RC030 | 30 | 8.00 ~ 60.00 | 单位：瓶/支 |

- 品类枚举 = [食品, 百货, 日化]（字段契约 enum，越枚举=黄灯）。
- 商品名称由生成器按固定词库+规格组合，无业务含义，不必逐个核对。
- **销售单价不在商品档案里**（门店自行定价，档案只有标准成本）——这是有意设计，
  销售成本一律用 `数量 × 商品.标准成本` 近似。

### 1.3 供应商（12 家）

GY001~GY012，名称为虚构公司名。结算方式枚举 = [月结30, 月结60, 现结]（越枚举=黄灯）。
每个商品由生成器固定指派一家主供应商；采购单的供应商编码 = 商品的指派供应商（除混沌 A5）。

### 1.4 门店在册商品（stocking）

每家在营门店在册 60 个商品（生成器 seeded 指派；为满足"每个商品至少 2 家门店在册"的
覆盖保证，部分门店会略多于 60）。**销售、采购、库存快照只发生在本店在册商品上**
（幽灵商品混沌 A4 除外）。库存快照 = 在册商品全集 × 12 个月，无缺行（约 5.8 千行，
以生成器为准）。

### 1.5 促销活动（参考档案，不入宽表）

约 28 条：门店 × 日期段 × 折扣力度（0.05~0.30）。**SPEC 简化声明：促销活动只做入口
契约校验（含混沌 A9 的 range 违规），不参与宽表 join——"日期段匹配"超出引擎声明式
等值 join 能力；销售行的折扣率直接落在流水上，与促销档案互不引用。**

---

## 2. 数据源清单（9 个源 + 1 个诱饵文件，全部由生成器产出到 `instances/retail/data/inbox/`）

> 事实期：**2025-09 至 2026-08，共 12 个完整自然月**。所有文件单文件承载全期数据，
> 文件名带导出月后缀 `_202608`（混沌条款：文件名月度后缀，验证 pattern 匹配）。
> CSV 编码 utf-8-sig；Excel 用 xlsxwriter 写入。

| # | 源 name | 文件（pattern） | 粒度 | 关键列 |
|---|---|---|---|---|
| 1 | fact_ledger 进销存台账 | 进销存台账_202608.csv | 行级（全部事项） | 事项类型/单据号/单据日期/门店编码/商品编码/供应商编码/渠道/数量/单价/折扣率/期末数量 |
| 2 | sales_flow 销售流水 | 销售流水_202608.csv | 单品行 | 流水号/销售日期/门店编码/商品编码/渠道/数量/单价/折扣率 |
| 3 | purchase_orders 采购单 | 采购单_202608.csv + **诱饵 采购单_202606.csv** | 单品行（单号跨行共享） | 采购单号/采购日期/门店编码/商品编码/供应商编码/数量/采购单价 |
| 4 | purchase_returns 采购退货 | 采购退货_202608.csv | 单品行 | 退货单号/退货日期/门店编码/商品编码/供应商编码/数量/退货单价 |
| 5 | stock_snapshots 库存快照 | 库存快照_202608.csv | 门店×商品×月末 | 快照月份/快照日期/门店编码/商品编码/期末数量 |
| 6 | stores 门店 | 门店.xlsx | 门店 | 门店编码/门店名称/城市/大区/开业日期 |
| 7 | products 商品 | 商品.xlsx | 商品 | 商品编码/商品名称/品类/单位/标准成本 |
| 8 | suppliers 供应商 | 供应商.xlsx | 供应商 | 供应商编码/供应商名称/结算方式 |
| 9 | promotions 促销活动 | 促销活动.xlsx | 门店×档期 | 门店编码/活动名称/开始日期/结束日期/折扣力度 |

**台账（fact_ledger）拼接规则（SPEC 权威定义）**：把 4 个事实文件按
销售流水→采购单→采购退货→库存快照顺序纵向拼接，列取并集（上表 #1 的 11 列），
各文件没有的列留空，**脏值原样保留**（千分位、空格编码等不修复）。映射：
销售行（事项类型=销售，单据号=流水号，单据日期=销售日期，单价，折扣率，渠道）；
采购行（=采购，单据号=采购单号，单价=采购单价）；退货行（=采购退货，单价=退货单价）；
库存行（=期末库存，单据号=SN-年月-店-品，单据日期=快照日期，期末数量）。
真实世界里这一步由 AI 装配脚本完成；本测试为消除装配变量，由生成器直接产出。
**为什么需要台账**：设计 §3.2 每实例一张宽表（一个 main 源），而进销存指标横跨四类
事实——只有台账这一张统一事实表能同时供给销售额/采购额/期末库存量。这是场景架构
决定，不是引擎缺陷。

**诱饵文件（A11）**：`采购单_202606.csv` 是 2026-06 前的旧导出，与
`采购单_202608.csv` 同时命中 pattern `采购单*.csv` → 按 mtime 最新取用（设计 N-01），
旧文件应 multi_match 黄灯留痕、**不落 raw**。生成器用 os.utime 显式保证 202606 的
mtime 早于 202608。

规模目标（生成器打印值为权威）：销售流水 ≈ 9.6 万行、采购 ≈ 6.5 千行（以销定采，
采购总量≈销售总量，进销自洽）、退货 ≈ 0.8 千行、库存快照 ≈ 5.8 千行、台账 ≈ 10.9 万行，
合计流水级 ≥ 10 万行，覆盖 12 个月。月末库存总量稳定在 12 万件量级（不爆仓不清零，
生成器内有断言）。

---

## 3. 字段契约与匹配契约（要求）

### 3.1 字段契约要点（逐字段完整定义见附录五配置基线）

- **red 级入口问题**：`file_missing / header_changed / empty_file / empty_after_clean` 全部 red。
- **比例阈值**：`row_drop_ratio {max: 0.01, yellow}`、`type_coerce_ratio {max: 0.005, yellow}`
  对两个事实大头（fact_ledger、sales_flow）生效。注入脏量已核算：单价文本化 15 行 ÷ 9.6 万
  ≈ 0.016%，远低于 0.5%——基线只留痕不升档；阈值升档是 TESTPLAN §3.1 R9 的破坏性用例。
- **unique 清单**：`sales_flow.流水号`、`purchase_returns.退货单号`（行级单号）与三个维表
  主键（门店/商品/供应商编码）。采购单号是单头号跨行共享，**不得**声明 unique
  （对照餐饮实例订单号的先例）；台账单据号只 required 不 unique（采购单号跨行共享的映射后果）。
- **missing: default 三处**：`折扣率`（default 0，两处：sales_flow 与 fact_ledger）、
  混沌 A3 即考察它。
- **range**：数量类 [1,1000]（销售）/ [1,100000]（采购退货）；折扣率 [0,1]；
  期末数量 [0,1000000]；折扣力度 [0,0.5]。全部 level: yellow（违规留痕不删行——
  设计 §7.1 层级灯色一致性）。混沌 A6/A7/A8/A9 考察"黄灯行保留"语义。
- **enum**：大区/品类/结算方式/事项类型/渠道，全部 level: yellow。

### 3.2 匹配契约要点（wide 装配，附录基线为准）

| join | keys | fanout | null_match | orphan_right | 理由 |
|---|---|---|---|---|---|
| stores | store_code | **red** | yellow | ignore | 维表键唯一性由生成保证；fanout red 防维表重复双计 |
| products | product_code | **red** | yellow | ignore | **混沌 A4 幽灵商品 → null_match 黄灯清单的主考察点** |
| suppliers | supplier_code | **red** | yellow | ignore | **黄灯基线**：销售/库存行供应商编码为空（业务上不涉及供应商），空键会进 null_match 清单——这是**预期基线 warn**，不是缺陷；真黄灯 = 混沌 A5 幽灵供应商 SUP-9999 |

---

## 4. 宽表装配与派生列（口径的家）

宽表 `wide_ledger`，main = fact_ledger，三个 left join（§3.2），派生列 9 个
（**expr 逐字以附录 wide.yml 为准**，此处给语义）：

| 派生列 | 语义 | 备注 |
|---|---|---|
| sales_net | 销售: round(数量×单价×(1−折扣率), 2)，其余事项 0 | 销售额口径=折后销售额 |
| sales_cost | 销售: round(数量×标准成本, 2)，其余 0 | **SPEC 简化声明：成本用商品标准成本近似，不做移动加权** |
| gross_profit | 销售: round(数量×单价×(1−折扣率)−数量×标准成本, 2)，其余 0 | 单行一次 round；幽灵商品行= NULL（数量×NULL） |
| sales_qty / sales_flag | 销售行数量 / 1，其余 0 | 行数与件数只数销售 |
| ecomm_net | 销售且渠道='电商' 的折后额，其余 0 | 渠道销售占比的分子 |
| purchase_amt / return_amt | 采购/退货行: round(数量×单价, 2)，其余 0 | |
| stock_qty | 库存行: coalesce(期末数量,0)，其余 0 | 混沌 A8 的 −10 会如实进入合计 |

**NULL 传染语义（SQL 语义，答案严格遵循）**：
- 派生列遇 NULL（幽灵商品的标准成本、千分位失败后的单价）→ 该行该派生列为 NULL；
- SQL `sum()` 跳过 NULL；**组内全 NULL 时 sum 结果是 NULL 而不是 0**；
- `else 0` 的分支保证非本类事项行贡献 0 而非 NULL。
- 由此产生的确定性结论：幽灵商品行计入销售额/数量/行数/动销，不计入成本与毛利
  （NULL 跳过）；千分位行计入数量/行数/动销，不计入任何金额。

---

## 5. 维度与指标（≥10，唯一出处）

### 5.1 维度（7 个）

月份（doc_date, time/month）、大区（region_name）、城市（city）、门店（store_name）、
品类（category）、渠道（channel）、供应商（supplier_name）。

### 5.2 指标（13 个，expr 以附录 metrics.yml 为准）

| 指标 | 公式（语义） | 类型 |
|---|---|---|
| 销售额 | sum(sales_net) | 金额 |
| 销售成本 | sum(sales_cost) | 金额 |
| 毛利 | sum(gross_profit) | 金额 |
| 毛利率 | round(sum(gross_profit)/nullif(sum(sales_net),0), 4) | 比率 |
| 销售数量 | sum(sales_qty) | 数量 |
| 销售行数 | sum(sales_flag) | 计数 |
| 动销商品数 | count(distinct case when entry_type='销售' then product_code end) | 计数 |
| 采购额 | sum(purchase_amt) | 金额 |
| 退货额 | sum(return_amt) | 金额 |
| 净采购 | sum(purchase_amt) − sum(return_amt) | 金额 |
| 期末库存量 | sum(stock_qty) | 数量 |
| 库存周转率 | round(sum(sales_cost)/nullif(sum(stock_qty),0), 4) | 比率 |
| 电商销售占比 | round(sum(ecomm_net)/nullif(sum(sales_net),0), 4) | 比率 |

**口径声明**：
- 销售成本=数量×标准成本（**设计决定，不要求移动加权**——避免超出引擎能力）。
- 库存周转率=当月销售成本÷当月末库存量（**简化口径**：月末静态库存，不做平均库存）。
- 渠道销售占比定义为**电商销售占比**（电商折后额÷总折后额）。在渠道月报中按渠道
  分组时该指标退化为组内比率（电商=1、门店=0、NULL 组 0/0=NULL）——这是聚合
  语义的确定性结果，不是缺陷。
- 设计未定义"促销跟随"：折扣率在流水上独立存在，与促销档案不联动（§1.5）。

---

## 6. 报表（6 张，定义以附录 dashboard.yml 为准）

| key | 标题 | 维度 | 时间 | 指标 | filters |
|---|---|---|---|---|---|
| monthly_kpi | 月度经营总览 | 月份 | 月份为维度 | 销售额/销售成本/毛利/毛利率/期末库存量/库存周转率/电商销售占比/动销商品数 | — |
| region_month | 大区月报 | 大区 | ×月份 | 销售额/净采购/毛利/毛利率 | 城市 |
| category_month | 品类月报 | 品类 | ×月份 | 销售额/销售数量/毛利/毛利率 | 大区 |
| channel_month | 渠道月报 | 渠道 | ×月份 | 销售额/毛利/电商销售占比 | — |
| store_rank | 门店排行 | 门店 | 无时间 | 销售额/毛利/毛利率/库存周转率 | 大区, 城市 |
| supplier_rank | 供应商采购排行 | 供应商 | 无时间 | 采购额/退货额/净采购 | — |

全部时间报表 `full_period_only: true`——本场景 12 个月全是完整月，该参数**不影响答案行集**。

**答案行集（密封答案的分组定义，SQL GROUP BY 语义，含 NULL 组与全零组）**：

| 报表 | 行数 | 说明 |
|---|---|---|
| monthly_kpi | 12 | 每完整月一行 |
| region_month | 36 | 3 大区 × 12 月；大区永不为 NULL |
| category_month | 48 | 4 组 × 12 月：食品/百货/日化 + **NULL 品类组**（混沌 A4 幽灵商品行，每月都有，销售额>0、毛利=NULL） |
| channel_month | 48 | 4 组 × 12 月：门店/电商/门店自提（混沌 A6）+ **NULL 渠道组**（采购/退货/库存行，销售额=0、电商占比=NULL） |
| store_rank | 8 | 8 家在营店；HB03 筹备店无流水 → 不出现 |
| supplier_rank | 13 | 12 供应商 + **NULL 供应商组**（空键基线 + 混沌 A5，采购额=SUP-9999 三行之和 >0） |

**引擎报表若在展示层隐藏全零组/NULL 组，对账时以 marts 层 SQL 语义（本节定义）为准。**
报表展示排序（是否按首指标降序等）属引擎/门户行为，**不进密封答案**（见 §8）。

---

## 7. 混沌条款

### 7.1 A 类：已注入数据内的脏与异常（基线数据自带，答案已计入其预期处理）

| # | 注入 | 行数 | 分布 | 预期处理（契约裁决） | 对答案的影响 |
|---|---|---|---|---|---|
| A1 | 销售流水·门店编码首尾空格（如 `" HD01 "`） | 25 | 12 个月散布 | `strip_strings` 清洗后与维表精确匹配，**正常入账** | 全额计入（清洗链路考察点） |
| A2 | 销售流水·单价文本化：`"1,234.50"` 式千分位（金额×1000 的分/元单位混乱）与 `"￥32.70"` 式货币符号，两种格式**必然**解析失败 | 15 | 12 个月散布，且保证每月每渠道合法行≥1 | **契约裁决：均为类型转换失败**（引擎未声明千分位/货币符号解析原语，v0.3 T3 先例同）→ 单价=NULL → 金额类派生列 NULL 被跳过 | 金额不计入；**数量/行数/动销照计**（不引用单价的派生列照常计算） |
| A3 | 销售流水·折扣率缺失 | 40 | 12 个月散布 | `missing: default 0` 补 0，行不丢 | 按**无折扣全额**计入 |
| A4 | 销售流水·幽灵商品 P9001×18、P9002×12 | 30 | 12 个月每月≥1 | 商品 join null_match **黄灯清单**必须出现 P9001/P9002；行保留、标签列 NULL | 计入销售额/数量/行数/动销；**不计入成本**；品类落 **NULL 组**（该组毛利/毛利率=NULL） |
| A5 | 采购单·幽灵供应商 SUP-9999 | 3 | 3 个不同月份 | 供应商 join null_match 黄灯清单出现 SUP-9999 | 采购额计入，供应商落 **NULL 组**（叠加 A12 基线） |
| A6 | 销售流水·渠道越枚举 `"门店自提"` | 12 | 每月恰 1 行 | enum 黄灯，**行保留**（设计 §7.1：黄→warn 测试不删行） | 渠道月报多出"门店自提"组，正常销售额 |
| A7 | 销售流水·数量=0 | 5 | 散布 | range [1,1000] 黄灯，行保留 | 销售额贡献 0，行数 +5 |
| A8 | 库存快照·期末数量=−10 | 1 | 生成器随机选一个原值≥30 的行（打印位置） | range [0,1000000] 黄灯，行保留 | 期末库存量 **−10** 如实进入合计，波及该店库存周转率 |
| A9 | 促销活动·折扣力度越界（1.50、0.90） | 2 | — | range [0,0.5] 黄灯；促销不入宽表 | 无报表影响（入口契约考察点） |
| A10 | 供应商·结算方式越枚举 `"季结90"` | 1 | GY012 | enum 黄灯 | 无报表影响 |
| A11 | 采购单双文件（202606 旧 + 202608 新） | — | mtime 旧<新 | 新文件胜出；旧文件 multi_match 黄灯留痕、不落 raw | 答案只认 202608 全量（=全部采购数据） |
| A12 | 台账销售/库存行供应商编码为空 | （结构性） | 全部销售/库存行 | 供应商 join null_match **预期基线 warn**（空键），不拦批 | 供应商 NULL 组的一部分 |
| A13 | 门店 HB03（筹备）零流水 | — | — | 维表有、流水无 | 不出现在任何报表分组；筛选白名单行为观察点（TESTPLAN §2.1 与 R11） |

**生成保证（可断言）**：门店/商品/供应商主键唯一；幽灵编码绝不在维表；采购/退货行
供应商除 A5 外全部在档；销售/采购/快照只发生在本店在册商品；快照=在册商品全集无缺行；
A2 的行不与 A4/A6/A7 重叠。

### 7.2 B 类：破坏性注入（仅 TESTPLAN 副本用例，基线数据不含，无数字答案）

红灯族：B1 门店.xlsx 重复门店行（fanout red → dbt error，build 失败）、
B2 重复流水号（unique 恒 red：ingest red + dbt error 双层，设计 §7.2）、
B3 商品.xlsx 表头改名（header_changed red）、B4 库存快照清空（empty_file red）、
B5 销售流水改名/删除（file_missing red，含"彻底改名两 pattern 全不命中"变体）。
装配族：B6 metrics 引用不存在列（ConfigError）、B7 dashboard 引用未知指标/维度（ConfigError）。
查询族：B8 维度名非法必须报错 / 维度值非法静默回退 / 注入串不得进 SQL（P-08、D14、§4.3）。
阈值族：B9 在销售流水追加 450 行文本化单价（同 A2 两种格式）使 type_coerce_ratio 破 0.5% → 黄灯升档留痕。
完整清单与步骤见 `../TESTPLAN.md`。

---

## 8. 密封标准答案（expected/answer.json）

- **独立性**：答案由生成器内**纯 pandas/Decimal 独立重算**（不复用引擎任何代码），
  从"契约处理后的真相"出发：A1 去空格、A3 补 0、A2 置 NULL、A4/A5 维表匹空、
  A6/A7/A8 黄灯行保留——与 §7.1 契约裁决逐条对应。
- **结构**：`{"<report_key>": {"columns": [维度列, 指标列...], "rows": [{列: 值}, ...]}}`，
  六张报表齐备，行集=§6 表（全维度值全月份）。
- **排序**：时间升序；同月内按维度值字符串升序，**NULL 组恒排最后**；无时间报表按维度值升序、NULL 最后。
- **数值**：金额 round 2、比率 round 4、数量/计数为整数；分母为 0 → null；
  组内全 NULL 的 sum → null；其余 null 一律 `null`。
  舍入用 Decimal ROUND_HALF_UP 逐行 replicate SQL `round(x, 2)`（先派生列逐行舍入、再求和）。
- **密封**：`expected/manifest.sha256` 记录 answer.json 的 SHA256；评审前重跑
  生成器必须得到同一哈希（固定 seed，逐字节可复现）。
- 答案中不含任何"脏行明细"——脏行的预期处置**只**通过它对组指标的贡献体现；
  脏行清单本身（黄灯名单、留痕）是行为断言，归 TESTPLAN。

---

## 9. 规模摘要（生成器打印值为权威）

- 数据源 9 个（+1 诱饵文件）；12 个完整月（2025-09 ~ 2026-08）。
- 流水级行数 ≥ 10 万（销售 ≈ 9.6 万 + 采购 ≈ 6.5 千 + 退货 ≈ 0.8 千 + 快照 ≈ 5.8 千；台账 ≈ 10.9 万）。
- 维度 7、指标 13、报表 6；密封答案 ≈ 165 行。
- 混沌：A 类 13 条（约 134 个脏行/异常文件），B 类 9 族破坏性用例。

## 10. 简化口径与能力边界声明（命题方自首清单）

1. 单宽表架构：进销存四类事实以台账形式统一进一张宽表（设计 §3.2 一实例一宽表的必然结论）。
2. 销售成本=数量×标准成本；库存周转率用月末静态库存。
3. 促销活动不入宽表（日期段匹配超引擎等值 join 能力）。
4. 应收/毛利不含税费；报表排序不进答案；全零组/NULL 组按 SQL 语义保留在答案中。
5. 千分位按"类型转换失败"裁决（引擎若选择解析千分位为合法数值，属超预期宽容，
   评审按"答案以契约裁决为准 + 实际行为如实记录"处理，不得回改答案）。

---

## 附录 A：五配置装配基线（测试 Agent 照此写入 instances/retail/）

> 语义内容（patterns/契约/expr/指标报表定义）必须与本基线一致；注释与格式可自定。
> instance.yml：

```yaml
name: retail
title: 荟品汇零售连锁
inbox: data/inbox
database: ../../../data/warehouse/retail.duckdb
tz: Asia/Shanghai
```

> sources.yml（9 源；事实源 problems 六件套，档案源三件）：

> wide.yml：

```yaml
version: 1
wide:
  name: wide_ledger
  main: fact_ledger
  joins:
    - table: stores
      keys: {left: store_code, right: store_code}
      how: left
      columns: [store_name, city, region_name, open_date]
      contract: {fanout: red, null_match: yellow, orphan_right: ignore}
    - table: products
      keys: {left: product_code, right: product_code}
      how: left
      columns: [product_name, category, std_cost]
      contract: {fanout: red, null_match: yellow, orphan_right: ignore}
    - table: suppliers
      keys: {left: supplier_code, right: supplier_code}
      how: left
      columns: [supplier_name]
      contract: {fanout: red, null_match: yellow, orphan_right: ignore}
      # 黄灯基线：销售/库存行供应商编码为空属预期；真黄灯=幽灵供应商 SUP-9999
  derived:
    - {name: sales_net,    expr: "case when entry_type = '销售' then round(quantity * unit_price * (1 - discount_rate), 2) else 0 end"}
    - {name: sales_cost,   expr: "case when entry_type = '销售' then round(quantity * std_cost, 2) else 0 end"}
    - {name: gross_profit, expr: "case when entry_type = '销售' then round(quantity * unit_price * (1 - discount_rate) - quantity * std_cost, 2) else 0 end"}
    - {name: sales_qty,    expr: "case when entry_type = '销售' then quantity else 0 end"}
    - {name: sales_flag,   expr: "case when entry_type = '销售' then 1 else 0 end"}
    - {name: ecomm_net,    expr: "case when entry_type = '销售' and channel = '电商' then round(quantity * unit_price * (1 - discount_rate), 2) else 0 end"}
    - {name: purchase_amt, expr: "case when entry_type = '采购' then round(quantity * unit_price, 2) else 0 end"}
    - {name: return_amt,   expr: "case when entry_type = '采购退货' then round(quantity * unit_price, 2) else 0 end"}
    - {name: stock_qty,    expr: "case when entry_type = '期末库存' then coalesce(ending_qty, 0) else 0 end"}
  drop: [_source_file, _loaded_at]
```

> dimensions.yml：

```yaml
version: 1
dimensions:
  - {name: 月份,   column: doc_date,      type: time, grain: month}
  - {name: 大区,   column: region_name,   type: category}
  - {name: 城市,   column: city,          type: category}
  - {name: 门店,   column: store_name,    type: category}
  - {name: 品类,   column: category,      type: category}
  - {name: 渠道,   column: channel,       type: category}
  - {name: 供应商, column: supplier_name, type: category}
```

> metrics.yml：

```yaml
version: 1
metrics:
  - {name: 销售额,       expr: "sum(sales_net)"}
  - {name: 销售成本,     expr: "sum(sales_cost)"}
  - {name: 毛利,         expr: "sum(gross_profit)"}
  - {name: 毛利率,       expr: "round(sum(gross_profit) / nullif(sum(sales_net), 0), 4)", format: percent}
  - {name: 销售数量,     expr: "sum(sales_qty)"}
  - {name: 销售行数,     expr: "sum(sales_flag)"}
  - {name: 动销商品数,   expr: "count(distinct case when entry_type = '销售' then product_code end)"}
  - {name: 采购额,       expr: "sum(purchase_amt)"}
  - {name: 退货额,       expr: "sum(return_amt)"}
  - {name: 净采购,       expr: "sum(purchase_amt) - sum(return_amt)"}
  - {name: 期末库存量,   expr: "sum(stock_qty)"}
  - {name: 库存周转率,   expr: "round(sum(sales_cost) / nullif(sum(stock_qty), 0), 4)"}
  - {name: 电商销售占比, expr: "round(sum(ecomm_net) / nullif(sum(sales_net), 0), 4)", format: percent}
```

> dashboard.yml：

```yaml
version: 1
reports:
  - key: monthly_kpi
    title: 月度经营总览
    dimension: 月份
    metrics: [销售额, 销售成本, 毛利, 毛利率, 期末库存量, 库存周转率, 电商销售占比, 动销商品数]
    chart: bar_line
    full_period_only: true
  - key: region_month
    title: 大区月报
    dimension: 大区
    time_dim: 月份
    metrics: [销售额, 净采购, 毛利, 毛利率]
    filters: [城市]
    chart: stack_bar
    full_period_only: true
  - key: category_month
    title: 品类月报
    dimension: 品类
    time_dim: 月份
    metrics: [销售额, 销售数量, 毛利, 毛利率]
    filters: [大区]
    chart: stack_bar
    full_period_only: true
  - key: channel_month
    title: 渠道月报
    dimension: 渠道
    time_dim: 月份
    metrics: [销售额, 毛利, 电商销售占比]
    chart: stack_bar
    full_period_only: true
  - key: store_rank
    title: 门店排行
    dimension: 门店
    metrics: [销售额, 毛利, 毛利率, 库存周转率]
    filters: [大区, 城市]
    chart: hbar
  - key: supplier_rank
    title: 供应商采购排行
    dimension: 供应商
    metrics: [采购额, 退货额, 净采购]
    chart: hbar
```
