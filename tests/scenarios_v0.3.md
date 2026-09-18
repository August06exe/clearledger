# v0.3 语义引擎验收测试题库（命题 Agent 出品，2026-09-19 夜航）

> 三权分立：命题 Agent 只读设计与配置出题（未读引擎代码）；测试 Agent 执行并记录；
> 评审 Agent 独立裁判。预期全部锚定 docs/语义层与多实例设计.md 条款，标注"设计未定义——考察点"处为开放考察。

## T1：客户编号首尾空格——清洗后必须能与维表精确匹配
- 场景：复制 `instances/sales` → `instances/_t_trim`，改 `instance.yml`（name: `_t_trim`，database 指向新库文件）。在 `_t_trim/data/inbox/sales_transactions.csv` 中挑 5 行，把客户编号改成带首尾空格的形式（如 `" C0001 "`，演示数据本身也预埋了此形态，可直接用原文件验证）。跑 ingest → compile → dbt build。
- 预期：设计 §3.1 `strip_strings` + §4.1（清洗在契约校验与落 raw 之前）：(1) raw 表 `WHERE customer_id != trim(customer_id)` 返回 0 行；(2) null_match 清单中不得出现去空格后明明存在的客户编号；(3) dbt build 整体绿。
- 考点：防"ID 带空格 → join 全匹空 → 报表整列 NULL 却绿灯"。

## T2：折扣率缺失——missing: default 必须补 0，行不得丢失
- 场景：`_t_trim` 实例，确认/制造 10 行折扣率为空的订单。全链路后查宽表 `int_wide_sales`。
- 预期：§3.1 `{missing: default, default: 0}` + §4.2：(1) 缺失行 `discount_rate = 0`；(2) `net_amount = amount`；(3) 行不丢失。
- 考点：防缺失被静默丢行或 NULL 传染 net_amount。

## T3：金额列混入千分位逗号——按比例定级、留痕不拦批
- 场景：`_t_trim` 两轮：300 行 `"1,299.00"`（0.18% < 0.5%）与 2500 行（1.5% > 0.5%）。各跑 ingest。
- 预期：§3.1 `type_coerce_ratio: {max: 0.005, level: yellow}`：(1) 两轮退出码均 0；(2) `raw.contract_report` 有 amount 转换失败计数明细；(3) 第二轮升级黄灯（呈现形式=考察点）；(4) 脏值行去向=考察点，但必须无痕消失即为不合格。
- 考点：千分位脏数据静默吞 NULL 且无报告；阈值必须是配置驱动。

## T4：range 与 enum 双违规——per_field 策略按字段留痕
- 场景：`_t_trim`：3 行数量改 `-5`/`0`；customers 2 行行业改 `"金融"`。ingest → compile → build。
- 预期：§3.1 `contract_violation: per_field`：(1) ingest 退出 0；(2) contract_report 区分 quantity range 与 industry enum 两类；(3) 编译产物含 industry 的 accepted_values 测试（severity/灯色=考察点：ingest 黄与 dbt 层是否一致）。
- 考点：负数量/越界枚举"看起来正常"；字段级策略退化为一刀切。

## T5：订单号空值与重复——required 剔除 + unique 双层防线
- 场景：`_t_trim` 追加 3 行：1 行订单号空、2 行订单号相同（DUP-001）。全链路。
- 预期：(1) ingest 层：required 缺失与 unique 重复进 contract_report（yellow，退出 0）；(2) staging 层：空订单号行不进宽表；(3) dbt 层：unique 测试 FAIL，build 退出码非零，红灯。
- 考点：重复订单双计收入；双层防线（ingest 留痕 + dbt 拦截）必须都真实成立。

## T6：文件名月度漂移——模式匹配找得到，彻底改名才红灯
- 场景：`_t_trim` 两次：(a) 改名 `sales_transactions_202609.csv`；(b) 改名 `明细202609_最终版.csv`（两模式均不命中）。各跑 ingest。
- 预期：§3.1 discover patterns：(a) 正常发现退出 0；(b) `file_missing: red` 退出非零，报错能定位到 sales_transactions 源。
- 考点：最常见的跑批翻车（月度文件名后缀）；"找不到却绿灯"或"红灯不知哪个源"。

## T7：表头变化与空文件——两种 red 入口问题都必须停批
- 场景：`_t_trim`：(a) customers.xlsx 列"行业"→"所属行业"；(b) org_structure.csv 清空（仅表头或 0 字节）。各跑 ingest。
- 预期：§3.1 problems：(a) `header_changed: red` 退出非零；(b) `empty_file: red` 退出非零。输出能区分问题类别与源（关键词=考察点）。
- 考点：上游改列名静默错列（设计点名的"防静默错列"）；空文件 0 行绿灯假象。

## T8：维表键重复（扇出）——fanout 编译为 error 级测试并拦下双计
- 场景：复制 `instances/sales` → `instances/_t_fanout`。customers.xlsx 为 C0001 增加一行重复（区域名不同）。ingest → compile → build。
- 预期：§3.2 `fanout: red` + §4.2：(1) 编译产物含 customers 右键 uniqueness 测试且 error 级；(2) 宽表行数膨胀（笛卡尔积），该测试 FAIL，build 退出非零；(3) `orphan_right: ignore` 不生成测试不报错。
- 考点：维表键重复收入双计静默过报表；必须真实编译成 error 测试。

## T9：主表键匹空——null_match 为 warn 级测试 + 清单，不拦批
- 场景：复制 → `instances/_t_nullmatch`。销售流水追加 2 行客户编号 `C9999`（维表不存在）。全链路。
- 预期：§3.2 `null_match: yellow`：(1) 编译产物生成"主表键不在维表"warn 级测试；(2) build 时 warn 呈现且能看到 C9999 清单，不失败；(3) 匹空行保留在宽表、标签列 NULL（left join 语义=考察点）；(4) 清单落地形式=考察点。
- 考点：新客户未建档时收入被静默丢弃或整批被拦；设计意图"黄灯+清单让人补档案"。

## T10：配置引用悬空——loader 交叉校验必须指名道姓地拒绝
- 场景：复制 → `instances/_t_dangling`。三处悬空：(a) metrics.yml 加 `{name: 退款额, expr: "sum(refund_amount)"}`；(b) dashboard.yml monthly_kpi.metrics 加 `净利润`；(c) industry_summary.dimension 改 `大区`。跑 compile。
- 预期：§2 loader 职责 + §4.3：编译失败（退出非零）或显式报错，且能定位到悬空引用本身（列/指标/维度名）；不得静默成功。（报错消息形态=考察点，重点"指名道姓"）
- 考点：配置演化断链（改了指标名看板还引用旧名）——五配置体系的底线能力。

## T11：筛选值注入与非白名单值——值非法静默回退，名非法必须报错
- 场景：sales 实例全链路后调用查询编译器： (a) `filters={区域: "华东' OR 1=1--"}`；(b) `filters={区域: "华东"}`；(c) 指标名 `不存在的指标`。
- 预期：(a) §4.3 白名单 + D14：不抛异常，SQL 无注入字面量，结果=全区域；(b) SQL 含筛选且结果仅华东（白名单不是全丢弃）；(c) §4.3 校验存在性：必须报错拒绝。"值非法宽容、名非法严格"不得混淆。
- 考点：SQL 注入；D14 静默回退被扩大化到指标/维度名。

## T12：双实例物理隔离——sales 与 restaurant 互不可见，引擎零改动
- 场景：两实例各自全链路；对比两库表清单；交叉查询同名报表 key `monthly_kpi`、同名维度"月份"（底层列 order_date vs order_time）、同名指标"毛利"（口径不同）；检查 `semantic/` `ingest/` `app/` 的 git diff。
- 预期：§2 + §1 目标4：(1) 两库表互不出现；(2) 查询结果互不串数据；(3) 同名不同义互不串口径；(4) 引擎目录 diff 为零。
- 考点：最致命事故——A 公司看到 B 公司的数字；"零业务预设"硬验收。

---
覆盖对照：字段契约 T1–T5；入口档案 T6–T7；匹配契约 T8–T9；配置校验 T10；查询与隔离 T11–T12。
