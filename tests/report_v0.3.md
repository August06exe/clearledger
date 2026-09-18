# v0.3 语义引擎验收测试报告（测试 Agent 出品，2026-09-19）

> 执行环境：Windows / Git Bash / `.venv/`（pandas 3.0.5, duckdb, dbt 1.12.5）。
> 三权分立角色：本报告只忠实记录实际操作、观察与判定；修复属主工程师；裁判属评审 Agent。
> 现场保留：临时实例 `instances/_t_trim`、`instances/_t_fanout`、`instances/_t_nullmatch`、`instances/_t_dangling`，
> 临时库 `data/warehouse/_t_*.duckdb`，基线投放区副本 `tests/_baseline_inbox/`，T11 脚本 `tests/_t11_query_test.py`——均未清理，供复查。
> 基线：开测前 `git status --short` 干净（仅 `?? tests/`）；`ops/doctor.py` 全绿。

---

## T1 客户编号首尾空格——清洗后必须能与维表精确匹配

**实际操作**
1. 复制 `instances/sales` → `instances/_t_trim`，`instance.yml` 改 `name: _t_trim`、database 指向 `../../../data/warehouse/_t_trim.duckdb`，清掉 pipeline/target、logs。
2. 在 `_t_trim/data/inbox/sales_transactions.csv` 前 5 行客户编号加首尾空格（`" C0089 "` 等；叠加演示数据自带的 300 行，共 305 行带空格）。
3. 依次执行：
   - `.venv/Scripts/python.exe -m semantic.ingest_run --instance _t_trim`
   - `.venv/Scripts/python.exe -m semantic.compile_dbt --instance _t_trim`
   - `cd instances/_t_trim/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors`

**观察**
- ingest 退出 0：`摄取完成: OK | 违规 0 项（yellow 0 / red 0 / pending 0）`，5 源全部 ok。
- compile 退出 0：`编译完成：24 个文件（变更 2 / 未变 22）`（变更仅 dbt_project.yml / profiles.yml，实例改名所致）。
- dbt build：`Done. PASS=35 WARN=0 ERROR=0 SKIP=0` 退出 0。
- **断言(1) 不符合**：`raw.sales_transactions WHERE customer_id != trim(customer_id)` 返回 **305 行**（预期 0 行）。raw 层保留原始空格。
- 断言(2) 符合：`raw.contract_report` 为空（无任何 null_match 假阳性记录）；宽表 `industry IS NULL` 行数 = 0，宽表 186331 行与 CSV 一致——去空格后存在的客户编号没有进匹空清单。
- 断言(3) 符合：build 全绿。
- 层次追踪：strip 实际发生在 **staging 编译物**（`stg_sales_transactions.sql` 中 `trim(cast(customer_id as varchar))`，compile_dbt.py TYPE_CAST 无条件 trim），raw 侧的 `strip_strings` 清洗原语没有生效。根因见 P-02：`apply_clean` 里 `if df[c].dtype == object` 在 pandas 3.0.5（`dtype=str` → StringDtype）下恒为 False，strip 从不执行（已用最小脚本复现：`strip SKIPPED: dtype is str`）。

**判定：部分符合**
- (1) 不符合：raw 未清洗（305 行带空格），"清洗在契约校验与落 raw 之前"未实现；
- (2)(3) 符合：终端保护目标（不错匹、不假阳性、绿灯真实）经由 staging trim 兜底达成。

**证据**：raw 305 行带空格样例 `('SO-20250401-0000001', '[ C0089 ]')` → stg 对应 `'[C0089]'`；宽表 0 行 industry NULL。

---

## T2 折扣率缺失——missing: default 必须补 0，行不得丢失

**实际操作**：使用 `_t_trim`（T1 链路已跑通）。演示数据自带 100 行折扣率为空（≥题目要求的 10 行），未另行制造。查 raw 与 `int_wide_sales`。

**观察**
- raw 层：`discount_rate IS NULL` = **100 行**，`= 0` = 186231 行——**ingest 层未补 0**（missing: default 的 fillna 没跑，根因 P-01）。
- 宽表层：100 个缺折扣订单全部在宽表（100/100），`discount_rate = 0`，`net_amount = amount` 的偏差行 0 个；宽表总行数 186331（不丢行）。补 0 实际由 **staging 编译物** `coalesce(cast(discount_rate as decimal(18,4)), 0)` 完成。
- 样例：`('SO-20250403-0000775', amount=1568.75, discount_rate=0.0000, net_amount=1568.75)`。

**判定：符合（就题面查宽表的三项断言全部成立）**
层次观察（设计未定义区）：补 0 发生在 staging 而非"落 raw 之前"（§4.1 字面），raw 层保留 NULL——与 P-01 同根因。

**证据**：`CSV 缺折扣率订单 100 个；宽表存在 100 个；其中 net_amount != amount 的 0 个`。

---

## T3 金额列混入千分位逗号——按比例定级、留痕不拦批

**实际操作**（两轮，均在 `_t_trim`，每轮前从 `tests/_baseline_inbox/` 恢复 CSV）
- 第一轮：300 行 `金额="1,299.00"`（300/186331 = 0.161% < 0.5%），跑 ingest。
- 第二轮：恢复基线后 2500 行（1.342% > 0.5%），跑 ingest。
- 附加：第一轮后跑了一次 dbt build 以追踪脏值下游去向。

**观察**
- 第一轮 ingest 退出 0，`违规 0 项`；`raw.contract_report` 行数 = **0**（无 amount 转换失败明细）。
- 第二轮 ingest 退出 0，`违规 0 项`；contract_report 仍 **0 行**——**1.34% > 0.5% 阈值没有任何黄灯升级**，`type_coerce_ratio` 从未触发。
- 脏值去向：raw 以 VARCHAR 原文保留（`contains(amount, ',')` = 300 / 2500 行；`try_cast(amount as decimal)` 失败同数）。
- 下游（附加 build）：`ERROR not_null_stg_sales_transactions_amount`，`Conversion Error: Could not convert string "1,299.00" to DECIMAL(18,4)`，`Done. PASS=28 WARN=0 ERROR=1` 退出 1。
- 根因：`validate_and_transform` 整体未执行（P-01），`pd.to_numeric`/type_coerce 计数/比例定级全部是死代码。

**判定：不符合**
- (1) 两轮退出码均 0——形式成立，但属"零检测"，非"比例定级后放行"；
- (2) contract_report 有 amount 明细——不成立（两轮皆空）；
- (3) 第二轮升级黄灯——不成立；
- (4) 脏值去向：**非无痕消失**（raw 留痕 + dbt 层红灯崩溃），但也不是设计的"黄灯放行"形态——是第三种形态：dbt 硬崩（Conversion Error），且契约报告无任何记录。考点"阈值必须是配置驱动"无法评估（阈值逻辑从未运行）。

**证据**：两轮 `违规 0 项` + contract_report 空表 + dbt Conversion Error 原文（见上）。

---

## T4 range 与 enum 双违规——per_field 策略按字段留痕

**实际操作**（`_t_trim`，先恢复两文件基线）
- `sales_transactions.csv` 前 3 行数量改 `-5 / 0 / -5`；`customers.xlsx` 前 2 行（C0001、C0002）行业改 `"金融"`（不在枚举 [制造业,零售连锁,互联网,教育培训,医疗健康,金融服务]）。
- ingest → compile → build。

**观察**
- ingest 退出 0，`违规 0 项`——**quantity range 与 industry enum 均未进 contract_report**（表为空）。
- raw 原样保留：`quantity in ('-5','0')` 3 行；`industry='金融'` 2 行。
- compile 退出 0（变更 0——编译物与配置无关变更）。`stg_customers.yml` 编译产物**含** industry 的 `accepted_values` 测试（值列表为 6 个合法枚举）。
- build：`FAIL 1 accepted_values_stg_customers_industry`，`ERROR=1`，退出 1——**error 级拦批红灯**。
- 考察点（severity/灯色一致性）：sources.yml 声明 `industry level: yellow`（预期 ingest 黄灯留痕不拦批）；实际 ingest 零留痕、dbt 层以**默认 error 级**测试直接拦批红灯。**ingest 黄与 dbt 层不一致，且配置的 level 语义没有传递到编译层**。
- quantity range：**全链路无任何检测**——raw 原样、编译物无 range 测试（gen_staging_yml 只生成 not_null/unique/enum）、若 enum 测试不拦，-5 会静默进宽表。负数量"看起来正常"的事故形态正是考点描述。

**判定：部分符合**
- (1) ingest 退出 0——形式成立（零检测）；
- (2) contract_report 区分两类违规——不成立（空表）；
- (3) 编译产物含 industry accepted_values——成立；severity 观察如上（不一致）。

**证据**：contract_report 0 行；raw `-5/0/金融` 原样；dbt `FAIL 1 accepted_values_stg_customers_industry ... ERROR=1`。

---

## T5 订单号空值与重复——required 剔除 + unique 双层防线

**实际操作**（`_t_trim`，先恢复基线）：追加 3 行——1 行订单号空、2 行订单号 `DUP-001`（金额不同）。ingest → （compile 无变更）→ build。

**观察**
- ingest 退出 0，`违规 0 项`；**contract_report 为空——required 缺失与 unique 重复均未留痕**（第一道防线缺位，P-01）。raw：空订单号 1 行（NULL）、DUP-001 2 行。
- staging：`空订单号 = 0 行`（stg 编译物 `where order_id is not null` 过滤生效，**空订单号行不进宽表**）；`DUP-001 = 2 行`（保留，交给测试拦截）。
- dbt：`FAIL 1 unique_stg_sales_transactions_order_id`，`ERROR=1`，退出 1，`SKIP=6`（下游宽表/marts 未物化）——**unique 测试 FAIL、红灯、退出非零成立**。

**判定：部分符合**
- (1) ingest 层进 contract_report——不成立（空表；退出 0 形式成立但属零检测）；
- (2) staging 剔除空订单号——成立；
- (3) dbt unique FAIL + 退出非零——成立。
- 双层防线实际只有 dbt 一层真实成立；"ingest 留痕"一层缺位。

**证据**：`stg 空订单号: (0)`、`stg DUP-001: (2)`、`Done. PASS=28 WARN=0 ERROR=1`。

---

## T6 文件名月度漂移——模式匹配找得到，彻底改名才红灯

**实际操作**（`_t_trim`，sales CSV 已恢复基线）
- (a) `sales_transactions.csv` → `sales_transactions_202609.csv`，跑 ingest。
- (b) 再改 `明细202609_最终版.csv`（两模式 `sales_transactions*.csv` / `销售明细*.csv` 均不命中），跑 ingest。

**观察**
- (a) `[ok] sales_transactions  sales_transactions_202609.csv  186331 行`，退出 0——模式匹配命中月度后缀文件。
- (b) `[FAIL] sales_transactions  -  - 行`，`摄取完成: RED`，退出 **1**；contract_report 明细：`(source=sales_transactions, rule=file_missing, level=red, sample="投放区 ...\instances\_t_trim\data\inbox 未匹配 ['sales_transactions*.csv', '销售明细*.csv']")`——源名与模式清单都在，能定位。

**判定：符合**（(a) 正常发现退出 0；(b) file_missing red 退出非零且定位到 sales_transactions 源）

**证据**：上行 contract_report 记录原文。

---

## T7 表头变化与空文件——两种 red 入口问题都必须停批

**实际操作**（`_t_trim`；先把 sales CSV 恢复原名）
- (a) `customers.xlsx` 列 `行业` → `所属行业`，跑 ingest。
- (b) `org_structure.csv` 清空为仅表头（94 字节），跑 ingest；附加变体：0 字节文件再跑一次。
- 每轮后恢复对应文件。

**观察**
- (a) `[FAIL] customers`，`摄取完成: RED`，退出 **1**；contract_report：`(customers, header_changed, red, "customers.xlsx 缺少声明的列: ['行业']")`——类别=header_changed、源=customers.xlsx、缺列名全部可定位。
- (b) 仅表头：`[FAIL] org_structure`，退出 **1**；contract_report：`(org_structure, empty_file, red, "org_structure.csv 为空文件")`。
- (b') 0 字节变体：**未捕获 `pandas.errors.EmptyDataError: No columns to parse from file` 直接崩溃**（traceback 退出 1），且：后续源 expenses **未被处理**（本轮只有 3 个源被读）、contract_report 无本轮流痕、`logs/ingest__t_trim_last.json` 未写。退出码 1 属于崩溃副作用，不是 `empty_file: red` 策略路径（策略路径要求先 `pd.read_csv` 成功）。

**判定：部分符合**
- (a) 符合；(b) 仅表头形态符合；0 字节形态不符合（异常终止 + 半途而废 + 无留痕，P-05）。

**证据**：两轮 contract_report 记录原文 + EmptyDataError traceback（见执行记录）。

---

## T8 维表键重复（扇出）——fanout 编译为 error 级测试并拦下双计

**实际操作**：复制 `instances/sales` → `instances/_t_fanout`（改名/改库同 T1）；`customers.xlsx` 复制 C0001 一行、区域改 `华南`（181 行）。ingest → compile → build。

**观察**
- ingest：`customers 181 行`，退出 0，`违规 0 项`——**维表键 unique:true 的 red 检测未触发**（P-01 旁证：重复 C0001 静默进 raw；若校验生效，ingest 应红灯）。
- compile 退出 0；产物 `tests/match_customers_fanout.sql` 首行 `{{ config(severity='error') }}`，SQL 为 `select customer_id from stg_customers group by 1 having count(*) > 1`——**error 级右键 uniqueness 测试成立**。
- build：`FAIL 1 match_customers_fanout` + `FAIL 1 unique_stg_customers_customer_id`（双保险），`ERROR=2`，退出 **1**；`int_wide_sales` 与全部 marts **SKIP**（库中 intermediate/marts 表清单为空）——双计数字未发布。
- (3) `orphan_right: ignore`：tests/ 目录只有 fanout + null_match 两类 4 个文件，**无 orphan 测试、无 orphan 报错**。
- 形态差异观察：题面预期"宽表行数膨胀（笛卡尔积）后测试 FAIL"；实际 dbt 在 staging unique 测试 FAIL 时即跳过下游，宽表**未物化**（膨胀被更早阻断）——保护效果等同且更优，但与题面描述的过程不同。

**判定：符合**（(1) error 级测试成立；(2) 测试 FAIL + 退出非零 + 双计被拦（宽表 SKIP 未物化）；(3) orphan 无测试无报错）

**证据**：`match_customers_fanout.sql` 内容、`Done. PASS=27 WARN=0 ERROR=2 SKIP=6`、`intermediate 表: []`。

---

## T9 主表键匹空——null_match 为 warn 级测试 + 清单，不拦批

**实际操作**：复制 → `instances/_t_nullmatch`；销售流水追加 2 行客户 `C9999`（NM-0001/NM-0002，维表无此客户）。ingest → compile → build。

**观察**
- 产物 `match_customers_null_match.sql` 首行 `{{ config(severity='warn') }}`，SQL 语义=主表键不在维表的 distinct 清单。✓
- build：`21 of 35 WARN 1 match_customers_null_match`，`Done. PASS=34 WARN=1 ERROR=0`，退出 **0**——warn 呈现、不失败。✓
- 宽表：186333 行全保留（CSV 186333）；C9999 两行 `customer_name/industry/region_name` 均 NULL、net_amount 正常（533.71 / 800.00）——left join 语义，匹空行不丢。✓
- **清单可见性（考察点）**：dbt 控制台/`logs/dbt.log` 只输出 `WARNING: Got 1 result, configured to warn if != 0`（计数）；`target/run_results.json` 记 `status: warn, failures: 1`（计数）。**C9999 值本身在任何标准产物中不可见**，需手工执行编译后的测试 SQL 才得到 `[('C9999',)]`。清单无自动落地（无表、无文件、无门户明细）。
- ingest 层：退出 0、无留痕（匹空属匹配契约，ingest 不管——与设计一致）。

**判定：符合**（(1)(2)(3) 成立；清单落地形式=半缺失，见 P-06）

**证据**：宽表 C9999 两行数据、dbt WARN 1 输出、手工执行测试 SQL 得 `[('C9999',)]`。

---

## T10 配置引用悬空——loader 交叉校验必须指名道姓地拒绝

**实际操作**：复制 → `instances/_t_dangling`；三处悬空一起上：(a) metrics.yml 加 `{name: 退款额, expr: "sum(refund_amount)"}`；(b) dashboard.yml monthly_kpi.metrics 加 `净利润`；(c) industry_summary.dimension 改 `大区`。跑 compile。随后为定位各自行为，分别单独测 (c)、(a)，以及 (a)+报表引用 退款额 的变体。

**观察**
- 三处齐上：compile 退出 **2**，`[config] 实例 [_t_dangling] 未声明指标: 净利润`——指名道姓 ✓（fail-fast 只报先遇到的 (b)，(c) 被遮蔽）。
- (c) 单独：退出 **2**，`[config] 实例 [_t_dangling] 未声明维度: 大区` ✓。
- (a) 单独（指标加了但无报表引用）：compile **静默成功退出 0**（`编译完成：24 个文件`）——悬空列 `refund_amount` 无人校验。
- (a) 变体（monthly_kpi.metrics += 退款额）：compile 仍退出 0，产物 `mart_monthly_kpi.sql` 第 8 行生成 `sum(refund_amount) as "退款额"`；错误延迟到 dbt build：`ERROR creating marts.mart_monthly_kpi`，`Binder Error: Referenced column "refund_amount" not found in FROM clause!`，退出 1——能定位列名，但发生在跑批期而非装配期。

**判定：部分符合**
- (b)(c) 完全符合（编译期拒绝 + 指名道姓）；
- (a) 不符合"编译失败或显式报错"的字面预期：compile 不设防、静默成功；防线退到 dbt build 的 Binder Error（属设计文档 §6 已知边界"expr 直通 SQL 无沙箱"，但题面预期更严）。

**证据**：三段退出码与报错原文（见上）。

---

## T11 筛选值注入与非白名单值——值非法静默回退，名非法必须报错

**实际操作**：sales 实例（marts 已就绪，值域确认 5 区域含 华东）。临时脚本 `tests/_t11_query_test.py` 调 `build_query/run_report/filter_options/load_instance`：
- (a) `filters={区域: "华东' OR 1=1--"}`
- (b) `filters={区域: "华东"}`
- (c) 报表 key `不存在的报表`；指标名 `不存在的指标`（loader 面）；维度名 `不存在的维度`（loader 面）；附加：filters 键传不存在的维度名。

**观察**
- (a) 不抛异常；SQL=`select * from marts.mart_region_month order by "月份" desc limit 500`，params=[]——**注入字面量未进 SQL**（`OR 1=1`/`--` 均不在）；结果 85 行、区域={华东,华中,华北,华南,西南}=全区域——非白名单值被静默忽略，等价无筛选。✓
- (b) SQL=`... where "区域" = ? order by ...`，params=['华东']（参数绑定）；结果 17 行、区域集合={'华东'}——白名单不是全丢弃。✓
- (c) 报表 key：`ConfigError: 实例 [sales] 无报表 不存在的报表`；指标名：`ConfigError: ... 未声明指标: 不存在的指标`；维度名：`ConfigError: ... 未声明维度: 不存在的维度`——名非法全部报错拒绝。✓
- 附加观察：`build_query` 的 filters **键**（维度名）非法时也走静默忽略（c4：`{'不存在的维度': '任意值'}` → 无 where、无报错）。"值非法宽容"被扩大到"筛选键名非法也宽容"——§4.3"校验 metric/dimension 存在"在 filters 键上未执行。

**判定：符合**（(a)(b)(c) 全部符合；键名宽容为边界观察，见 P-08）

**证据**：脚本输出全文（SQL 原文、params、行数、区域集合、三条 ConfigError）。

---

## T12 双实例物理隔离——sales 与 restaurant 互不可见，引擎零改动

**实际操作**
1. 两实例各自全链路（ingest → compile → dbt build）：
   - sales：ingest 退出 0（5 源）→ compile 0（变更 0）→ build `PASS=35 WARN=0 ERROR=0` 退出 0。
   - restaurant：ingest 退出 0（orders 427938 行 + dishes + stores）→ compile 0 → build `PASS=26 WARN=0 ERROR=0` 退出 0。
2. 对比 `sales.duckdb` 与 `restaurant.duckdb` 表清单；交叉调 `run_report` 查同名 key `monthly_kpi`；对比同名维度 月份（order_date vs order_time）与同名指标 毛利 的编译口径；`git diff` 引擎目录。

**观察**
- 表清单：sales 库（int_wide_sales + 5 marts + 6 raw + 5 staging）与 restaurant 库（int_wide_orders + 5 marts + 3 raw + 3 staging）**互不出现对方任何表**；唯一同名 `marts.mart_monthly_kpi` 分属两个物理库文件。
- 交叉查询：sales monthly_kpi 列={月份,收入,成本,毛利,毛利率}（毛利 2.0 亿级/月）；restaurant monthly_kpi 列={月份,营业额,毛利,毛利率,客单数}（毛利 135 万级/月）——列集与量级完全不同，无串数据。
- 同名不同义：月份 sales→`date_trunc('month', order_date)`、restaurant→`date_trunc('month', order_time)`，各自出数；毛利 两实例 wide.yml 派生式不同（sales: `amount*(1-discount_rate)-quantity*std_cost`；restaurant: `amount-quantity*std_cost`），毛利率分母分别为 `net_amount` 与 `amount`——口径各自正确，无串口径。
- 引擎零改动：`git diff --stat -- semantic/ ingest/ app/` 输出为空；工作区仅 `instances/*/pipeline/target/*`（dbt 构建产物）与未跟踪的临时实例/tests。

**判定：符合**（(1)(2)(3)(4) 全部成立）

**证据**：两库表清单、两实例 monthly_kpi 前三行数据、两个 mart_monthly_kpi.sql 毛利编译行、git diff 空。

---

# 汇总表

| 题号 | 标题 | 判定 |
|---|---|---|
| T1 | 客户编号空格清洗匹配 | **部分符合** |
| T2 | 折扣率缺失补 0 | **符合** |
| T3 | 千分位按比例定级 | **不符合** |
| T4 | range/enum 双违规 | **部分符合** |
| T5 | 订单号空值+重复 | **部分符合** |
| T6 | 文件名月度漂移 | **符合** |
| T7 | 表头变化与空文件 | **部分符合** |
| T8 | 维表键重复扇出 | **符合** |
| T9 | 主表键匹空清单 | **符合** |
| T10 | 配置引用悬空 | **部分符合** |
| T11 | 筛选注入与非白名单 | **符合** |
| T12 | 双实例物理隔离 | **符合** |

计数：符合 6 / 部分符合 5 / 不符合 1。

# 发现的问题清单

**P-01（严重，建议阻断 v0.3 验收）字段契约校验整体失效——`validate_and_transform` 是死代码**
- 描述：`semantic/ingest_run.py` 中 `df = df.rename(columns=col_map)`（L184，中文列名→英文 map）先于 `df = validate_and_transform(df, fields, ...)`（L192）执行；而 validate 内部按 `cn`（中文列名）查 `if cn not in df.columns: continue`——rename 后列名已是英文 map，**每个字段都 continue，逐字段契约校验（type/range/enum/format/required/unique/missing）一行都没跑**。
- 证据（六处独立实证）：
  - T2：raw.discount_rate 100 行 NULL（missing:default 的 fillna 未跑）；
  - T3：两轮千分位 `违规 0 项`、contract_report 空（type_coerce 计数/比例定级未跑）；
  - T4：quantity -5/0 与 industry 金融零记录（range/enum 未跑）；
  - T5：空订单号/重复订单号零记录（required/unique 未跑）；
  - T8：customers 重复 C0001 摄取 `违规 0 项`（维表键 unique:red 未跑）；
  - 决定性证据：`_t_trim` 库 raw.sales_transactions **全部列类型 VARCHAR**（若 validate 生效，date/integer/decimal 列应已被 pd 类型化——order_date/quantity/amount 全是字符串）。
- 影响：v0.3 核心卖点"字段契约"在 ingest 层完全不工作；raw 层是无类型字符串堆。目前全靠 staging 编译物（trim/cast/coalesce/where）与 dbt 测试兜底，属"防线错位"而非"双防线"。
- 严重度建议：严重（P0）。

**P-02（高）`strip_strings` 清洗原语在 pandas 3 下失效**
- 描述：`apply_clean` 的 `if df[c].dtype == object` 在 pandas 3.0.5（`read_csv(dtype=str)` → StringDtype）下恒为 False，strip 与 `replace({"":None,"nan":None})` 从不执行。
- 证据：T1——raw 305 行 `customer_id != trim(customer_id)`；最小复现脚本输出 `strip SKIPPED: dtype is str`。
- 影响：设计 §3.1/§4.1"清洗在落 raw 之前"未实现；与 §4.1 字面相悖（目前靠 staging trim 兜底掩盖）。
- 严重度建议：高（P1）。

**P-03（中）range 契约没有任何编译物**
- 描述：`compile_dbt.gen_staging_yml` 只生成 not_null/unique/enum 测试，sources.yml 的 `range: [1,1000000]` 不编译为任何 dbt 测试；叠加 P-01 后，负数量/越界值全链路零检测零留痕。
- 证据：T4——quantity=-5/0 原样进 raw、无测试、无记录；compile_dbt.py 全文无 range 相关生成逻辑。
- 严重度建议：中。

**P-04（中）字段级 `level` 配置语义未传递到 dbt 编译层，ingest 黄与 dbt 红不一致**
- 描述：sources.yml `industry level: yellow` 表达"留痕不拦批"，但编译的 accepted_values 测试用 dbt 默认 error 级，直接拦批红灯；且 ingest 层因 P-01 根本不报黄。
- 证据：T4——`FAIL 1 accepted_values_stg_customers_industry`，ERROR=1 退出 1。
- 严重度建议：中（设计意图与实现行为的口径需评审拍板：enum 到底黄还是红）。

**P-05（中）0 字节文件未捕获 EmptyDataError，跑批半途崩溃**
- 描述：`read_file` 对 0 字节 CSV 直接抛 `pandas.errors.EmptyDataError`，未被 `empty_file: red` 策略路径捕获；崩溃导致：后续源（expenses）未处理、本轮 contract_report 零留痕、`logs/ingest_<inst>_last.json` 未写。仅表头文件（0 数据行）走正常 red 路径。
- 证据：T7 0 字节变体 traceback 原文。
- 严重度建议：中（退出码碰巧非零，但留痕与"每个源独立定级"的设计承诺被破坏）。

**P-06（中）null_match "清单"无自动落地，只有 WARN 计数**
- 描述：匹空 ID 清单（设计意图"黄灯+清单让人补档案"）在 dbt 控制台/日志/run_results.json 中只有计数（`Got 1 result`），C9999 值需手工执行编译后的测试 SQL 才可见；无落地表/文件/门户明细。
- 证据：T9——grep dbt.log 与 run_results.json 均无 C9999 字面量；手工执行得 `[('C9999',)]`。
- 严重度建议：中（清单是设计点名的半成品）。

**P-07（低）指标 expr 列引用编译期不校验，悬空列延迟到跑批期爆炸**
- 描述：loader 校验 metric/dimension **名**存在性（T10b/c 证实有效），但不校验 expr 引用的**列**；悬空列的 mart SQL 被正常生成，dbt build 期 Binder Error 才暴露。
- 证据：T10a——compile 退出 0 且产物含 `sum(refund_amount)`；build 期 `Binder Error: Referenced column "refund_amount" not found`。
- 严重度建议：低（设计 §6 已知边界，但与题面"装配期拒绝"预期有差距，评审需拍板是否收紧）。

**P-08（低）build_query 对 filters 键名（维度名）非法也静默忽略**
- 描述：非白名单**值**静默回退是 D14 决策；但 filters 的**键**若是不存在的维度名，同样静默忽略不报错——"值宽容"被扩大到"键宽容"，与 §4.3"校验 dimension 存在"的严格面不完全一致。
- 证据：T11-c4——`{'不存在的维度': '任意值'}` → 无 where、params=[]、无异常。
- 严重度建议：低（边界拍板项）。

**P-09（低，工程细节）`semantic.query` CLI 无参数解析**
- 描述：`python -m semantic.query --help` 把 `--help` 当实例名，抛 `ConfigError: 实例不存在`；无 usage/帮助输出。
- 证据：T11 准备阶段首次调用输出。
- 严重度建议：低。

---

## 附：现场清单（评审 Agent 复查用）

- 临时实例：`instances/_t_trim`（T1-T7，inbox 已恢复基线，库保留各轮 contract_report 痕迹——注意 contract_report 是按轮 insert 累积的，本轮 T7 最后一次全绿摄取后仅剩历史问题记录可查）、`instances/_t_fanout`（T8）、`instances/_t_nullmatch`（T9）、`instances/_t_dangling`（T10，dashboard.yml 现为"monthly_kpi 引用退款额"变体态）。
- 临时库：`data/warehouse/_t_trim.duckdb`、`_t_fanout.duckdb`、`_t_nullmatch.duckdb`、`_t_dangling.duckdb`。
- 基线副本：`tests/_baseline_inbox/`（与 instances/sales/data/inbox 初始态一致，唯 sales_transactions.csv 为原始未加空格版——T1 的 5 行加空格只在 _t_trim 实例内做的）。
- T11 脚本：`tests/_t11_query_test.py`。
- sales / restaurant 两实例已各自重新全链路（T12），配置零改动；引擎目录（semantic/ ingest/ app/）git diff 为空。

---

## 复测纪要（主工程师，修复 P-01/P-02/P-03/P-04/N-01/N-02/N-03/N-04/N-06/N-07/N-08/N-09/N-10/P-07/P-08/P-09 后）

| 原判定 | 场景 | 复测结果 |
|---|---|---|
| T1 部分 | 空格清洗 | ✅ strip_strings 兼容 pandas3 StringDtype；raw 无带空格 ID；两实例重建后对数仍 0.0000 差 |
| T3 不符合 | 契约校验死代码 | ✅ **复活**：raw 列类型化（TIMESTAMP/BIGINT/DOUBLE）；注入 2500 千分位+3 越界 → contract_report 记录 type_coerce(2500)/required_missing_dropped(2500)/range(3)/type_coerce_ratio/row_drop_ratio 全留痕 |
| T4 部分 | range 无编译物 / enum 灯色不一致 | ✅ range 编译为 dbt 测试（severity 按字段 level）；accepted_values 带 severity: warn（level=yellow 时）——ingest 与 dbt 灯色一致 |
| T5 部分 | unique 双层防线 | ✅ 实测 _t_fanout：ingest RED（unique 违规 red）+ dbt match_fanout FAIL + unique 测试 FAIL → ERROR=2、下游 SKIP=6，双层拦截成立 |
| T7 部分 | 0 字节崩溃 | ✅ EmptyDataError 显式捕获 → read_failed red 留痕；单源崩溃不拖垮整轮（N-02 每源隔离） |
| T10 部分 | 悬空引用静默 | ✅ loader 新增标识符启发式：expr 引用宽表不存在列 → ConfigError 指名道姓（装配期拦截） |
| T11 符合 | 边界加固 | ✅ 注入值忽略（85==85）；名非法报错（列可用维度清单）；时间维度可筛选（N-10） |
| Q-01 空真 | orphan_right | ✅ yellow → 生成 warn 级孤儿清单测试；ignore → 跳过（N-03）；fanout: ignore → 跳过（N-04） |
| N-01 | 多文件遮蔽 | ✅ mtime 最新优先 + multi_match 黄灯留痕全部候选（实测 3 文件场景） |

**回归**：sales 37/37 全绿、restaurant 27/27 全绿；对数复核 0.0000 差。其余修复：库不存在显式报错（N-06）、logs 绝对路径（N-07）、profiles 绝对路径（N-08）、缺键 ConfigError（N-09）、query CLI argparse（P-09）。

**遗留（工程债台账，不阻断）**：P-06 匹空清单的门户级落地（现 dbt 测试可查）；missing:default 填充计数留痕。

**闸门结论（复测后）**：评审三项必修（P-01/N-01/N-02）全部修复并实证；七项拍板项已定谳写入设计文档 §7。v0.3 语义引擎**具备验收条件**，待晨间人类验收。
