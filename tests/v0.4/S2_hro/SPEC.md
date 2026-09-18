# S2 场景圣经：睿才人力（人力资源外包服务商）

> 命题 Agent 出品（三权分立·命题方）。本文档是 S2 场景的**唯一权威**：
> 业务事实、字段契约、匹配契约、指标口径、报表定义、混沌条款、密封答案规则均以此为准。
> 测试 Agent 据此装配实例 `instances/hro/` 并执行 `../TESTPLAN.md`；
> 评审 Agent 据此对照 `expected/answer.json` 独立裁判。
> 引擎能力边界一律锚定 `docs/语义层与多实例设计.md`（下称"设计"）；
> 凡引擎声明能力之外的诉求，本文显式声明简化口径，不构成扣分项。

---

## 0. 一句话场景

睿才人力是一家人力资源外包服务商：把外派员工派驻到客户现场，按"外派人数 × 月服务费"
向客户开月度账单，按月回收款。公司 3 个事业部、6 个交付组，服务 24 家客户、40 份合同、
近万名外派员工。管理层要看：开了多少账单、收回多少钱、还压多少应收、养多少人、
成本多少、毛利几何、人均产值多少。

---

## 1. 组织与主数据（完整虚构，生成器硬编码，禁止改动）

### 1.1 组织

| 事业部编码 | 事业部名称 | 负责人 | 交付组 |
|---|---|---|---|
| BU-FIN | 金融事业部 | 沈国峰 | GR-F01 金融一组、GR-F02 金融二组 |
| BU-NET | 互联网事业部 | 陆佳炜 | GR-N01 互联网一组、GR-N02 互联网二组 |
| BU-MFG | 制造业交付事业部 | 韩志强 | GR-M01 制造一组、GR-M02 制造二组 |

### 1.2 客户（24 家）

| 行业 | 家数 | 客户级别分布 |
|---|---|---|
| 金融 | 7 | A×3 B×3 C×1 |
| 互联网 | 7 | A×2 B×3 C×2 |
| 制造 | 6 | A×1 B×3 C×2 |
| 零售 | 3 | B×1 C×2 |
| 文体（混沌 H8） | 1 | C×1（越枚举，yellow 保留） |

- 行业枚举 = [金融, 互联网, 制造, 零售]；客户级别枚举 = [A, B, C]；越枚举 = 黄灯。
- 混沌 H9：另有一家正常行业客户的级别被改为 `"S级"`（越枚举，yellow）。
- 客户名称为虚构公司名（如"汇金证券股份有限公司"），无业务含义。

### 1.3 合同（40 份）

- 编码 `HT-0001 ~ HT-0040`；每客户 1~2 份。
- 列：合同号 / 客户编码 / 签约事业部编码 / 签约事业部名称（**刻意反规范化**，宽表
  无需为事业部再挂一跳 join）/ 月服务费（元/人·月）/ 开始月 / 结束月（`YYYY-MM` 字符串，
  format 正则契约）。
- 月服务费（元/人·月）：**按合同初期在册人均月薪资成本上浮 12%~28% 定价**（生成器内
  seeded 取值，rounded 到十元）——保证每份合同毛利率落在约 10%~28% 的正区间，
  全司毛利率约 15%~22%。
- 起止月分布：多数覆盖全观察期；**2 份期中起租**（起月 2026-01 / 2026-03，
  其中混沌 H2 在起月前一月即开票）；**6 份提前截止**（止月 2026-01 ~ 2026-04，
  其中 4 份被混沌 H1 选中超止月开票）；**2 份未来合同**（起月 2026-10 / 2026-11，
  观察期内零台账活动——合同台账报表中**应缺席**，这是分组语义的确定性结论）。
- 事业部归属口径：**签约事业部**（来自合同），交付组只影响员工归属。为什么：
  账单/回款行没有交付组，若用"交付组→事业部"做收入归属，收入将全部落 NULL 组。
  SPEC 拍板：收入/成本/毛利按签约事业部归属；交付组维度只服务花名册侧指标
  （外派人数、人力成本、人均人力成本）。

### 1.4 外派花名册（月度在册，10 万行级）

- **粒度 = 员工 × 月份**（当月在册才有一行）。列：员工编号 / 姓名 / 月份 / 交付组编码 /
  合同号 / 岗位 / 月薪资成本。
- **月薪资成本 = 工资+社保+公积金合并列**（任务书定义），按岗位档位 seeded：
  项目经理 15500~19500（约 5%）、软件开发工程师 9800~13800（25%）、测试工程师
  7200~10200（20%）、运维工程师 6800~9500（15%）、客户服务专员 5200~7200（20%）、
  数据处理专员 4600~6400（20%）；同一员工各月恒定。
- 员工池 ~1.1 万人（含流失再生）；在册人数随合同人数目标逐月漂移（增长 + seeded 波动），
  在册行数 ≈ 12.2 万——S2 的"流水级"就是员工月度在册；账单/回款是月度汇总粒度
  （任务书明确"直接给数"），这是业务本性，不是数据偷懒。
- 花名册行的合同号全部指向真实合同（除混沌 H3 的 HT-9999）。

### 1.5 账单与回款

- 月度账单 = 月份 × 合同 × 账单金额，金额 = **当月该合同在册人数 × 月服务费**（汇总结果
  直接落数），rounded 2；观察期 2025-09 ~ 2026-08 共 12 个月。
- 回款记录 = 月份 × 合同 × 回款金额；每份正常账单以 ~87% 概率回款，
  金额 = 账单 × U(0.90, 1.00)。由此全司回款率落在 0.75~0.90 区间，应收余额逐月为正。
- 千分位脏账单（H5）无对应回款（"未确认账单"业务口径），避免局部回款率>1 的语义噪音。

---

## 2. 数据源清单（8 个源 + 1 个诱饵文件，全部由生成器产出到 `instances/hro/data/inbox/`）

> 事实期：**2025-09 至 2026-08，共 12 个完整自然月**。文件名带导出月后缀 `_202608`。
> CSV 编码 utf-8-sig；花名册按任务书要求为 **xlsx**（10 万行级大表，考察 Excel 摄取吞吐）。

| # | 源 name | 文件（pattern） | 粒度 | 关键列 |
|---|---|---|---|---|
| 1 | hro_ledger 经营台账 | 经营台账_202608.csv | 行级（全部事项） | 事项类型/单据号/单据月份/合同号/交付组编码/员工编号/姓名/岗位/月薪资成本/金额 |
| 2 | business_units 事业部 | 事业部.xlsx | 事业部 | 事业部编码/事业部名称/事业部负责人 |
| 3 | delivery_groups 交付组 | 交付组.xlsx | 交付组 | 组编码/组名称/所属事业部编码 |
| 4 | customers 客户 | 客户.xlsx | 客户 | 客户编码/客户名称/行业/客户级别 |
| 5 | contracts 合同 | 合同.xlsx | 合同 | 合同号/客户编码/签约事业部编码/签约事业部名称/月服务费/开始月/结束月 |
| 6 | roster 外派花名册 | 外派花名册_202608.xlsx | 员工×月份 | 员工编号/姓名/月份/交付组编码/合同号/岗位/月薪资成本 |
| 7 | bills 月度账单 | 月度账单_202608.csv | 月份×合同 | 月份/合同号/账单金额 |
| 8 | payments 回款记录 | 回款记录_202608.csv + **诱饵 回款记录_202607.csv** | 月份×合同 | 月份/合同号/回款金额 |

**台账（hro_ledger）拼接规则（SPEC 权威定义）**：账单行 + 回款行 + 花名册行三合一，
列取并集（上表 #1 的 10 列），各文件没有的列留空，脏值原样保留。映射：
账单行（事项类型=账单，单据号=BL-年月-合同号，单据月份=月份，金额=账单金额）；
回款行（=回款，单据号=PY-年月-合同号，金额=回款金额）；
在册行（=在册，单据号=RS-年月-员工编号，交付组编码/员工编号/姓名/岗位/月薪资成本，
**金额留空**）。
**为什么需要台账**：设计 §3.2 一实例一张宽表（一个 main 源）；收入（账单）、回款、
人力成本（在册）必须在同一张事实表上才能同组聚合出毛利/回款率/人均产值。
单据月份一律取**月首日期**（如 2025-09-01），供 time/month 维度使用。

**诱饵文件（H11）**：`回款记录_202607.csv` 旧导出与 `回款记录_202608.csv` 同命中
pattern → mtime 最新胜出（设计 N-01），旧文件 multi_match 黄灯留痕、不落 raw。
生成器用 os.utime 显式保证 mtime 顺序。

规模目标（生成器打印权威值）：花名册 ≈ 12.2 万行、账单 ≈ 420 行、回款 ≈ 360 行、
台账 ≈ 12.3 万行；覆盖 12 个月。

---

## 3. 字段契约与匹配契约（要求）

### 3.1 字段契约要点（逐字段完整定义见附录五配置基线）

- **red 级入口问题**：`file_missing / header_changed / empty_file / empty_after_clean` 全部 red。
- **比例阈值**：`row_drop_ratio {max: 0.01, yellow}`、`type_coerce_ratio {max: 0.005, yellow}`
  对 hro_ledger、roster、bills 三个事实源生效。注入脏量已核算：千分位 6 行 ÷ 台账
  12.3 万 ≈ 0.005%，远低于 0.5%——基线只留痕；升档是 TESTPLAN §3.2 H8 的破坏性用例。
- **unique 两处**：`contracts.合同号`、`hro_ledger.单据号`（三个事实源单号规则互不重叠、
  天然全局唯一）+ 维表主键（事业部/交付组/客户编码）。roster **不得**声明 unique
  （员工跨月重复是在册表的本性）。
- **missing: default 三处**：roster.岗位 与 ledger.岗位（default `未分类`）、
  roster.月薪资成本 与 ledger.月薪资成本（default 0）——混沌 H6/H7 考察。
- **range**：月服务费 [1000, 100000]、月薪资成本 [0, 100000]、回款金额 [0, 100000000]、
  账单金额 [0, 100000000]，全部 level: yellow。混沌 H10 的 **−500 负回款** 是
  "黄灯行保留、数值如实进入合计"的考察点。
- **enum**：行业、客户级别、事项类型，全部 level: yellow（黄灯行保留 → 生成新分组）。
- **format**：合同.开始月/结束月 用 `^\d{4}-\d{2}$` 正则契约（越格式=黄灯）。

### 3.2 匹配契约要点（wide 装配，附录基线为准）

| join | keys（左列来源） | fanout | null_match | orphan_right | 理由 |
|---|---|---|---|---|---|
| contracts | contract_no（主流水列） | **red** | yellow | ignore | 合同号唯一生成保证；**混沌 H3/H4 幽灵合同 HT-9999/HT-8888 → 黄灯清单主考察点** |
| customers | customer_code（**来自 contracts join，有序 join 依赖**，设计 §3.2"有序左联"） | **red** | yellow | ignore | 合同→客户的二级行业/级别标签；若引擎不支持 join-on-joined-column，属**引擎能力缺口**，如实记录（见 §10.5） |
| groups | group_code（主流水列，账单/回款行为空） | **red** | yellow | ignore | **黄灯基线**：账单/回款行无交付组（空键）属预期 warn；真黄灯只有幽灵合同行的连锁匹空 |

---

## 4. 宽表装配与派生列（口径的家）

宽表 `wide_hro`，main = hro_ledger，三个 left join（§3.2），派生列 4 个
（**expr 逐字以附录 wide.yml 为准**）：

| 派生列 | 语义 |
|---|---|
| bill_amt | 账单行: coalesce(金额,0)，其余 0 |
| pay_amt | 回款行: coalesce(金额,0)，其余 0 |
| cost_amt | 在册行: coalesce(月薪资成本,0)，其余 0 |
| gross_amt | 账单行: +金额；在册行: −月薪资成本；其余 0 |

**NULL 传染语义（SQL 语义，答案严格遵循）**：
- 千分位账单（H5）金额转换失败 → NULL → `coalesce(金额,0)=0` → **收入不计**，
  但在单合同数/在单客户数（count distinct 合同号/客户码）**照计**（不引用金额）。
- 幽灵合同行（H3/H4）的合同侧标签（客户编码/签约事业部名称/月服务费/起止月）全 NULL，
  连锁导致行业/级别/客户名称 NULL；行保留，金额/人数/成本**如实计入对应 NULL 组**。
- `else 0` 分支保证非本类事项贡献 0 而非 NULL；组内全 NULL 的 sum 结果是 NULL 不是 0
  （本架构派生列恒有 else 0，故仅 count/ratio 路径可能出 NULL）。

---

## 5. 维度与指标（≥10，唯一出处）

### 5.1 维度（7 个）

月份（doc_month, time/month）、事业部（bu_name）、交付组（group_name）、
客户（customer_name）、行业（industry）、客户级别（customer_level）、合同（contract_no）。

### 5.2 指标（12 个，expr 以附录 metrics.yml 为准）

| 指标 | 公式（语义） | 类型 |
|---|---|---|
| 服务费收入 | sum(bill_amt) | 金额 |
| 回款额 | sum(pay_amt) | 金额 |
| 回款率 | round(sum(pay_amt)/nullif(sum(bill_amt),0), 4) | 比率 |
| 应收余额 | sum(bill_amt) − sum(pay_amt) | 金额 |
| 人力成本 | sum(cost_amt) | 金额 |
| 毛利 | sum(gross_amt) | 金额 |
| 毛利率 | round(sum(gross_amt)/nullif(sum(bill_amt),0), 4) | 比率 |
| 外派人数 | count(distinct case when entry_type='在册' then employee_no end) | 计数 |
| 人均产值 | round(sum(bill_amt)/nullif(count(distinct case when entry_type='在册' then employee_no end),0), 2) | 金额 |
| 人均人力成本 | round(sum(cost_amt)/nullif(count(distinct case when entry_type='在册' then employee_no end),0), 2) | 金额 |
| 在单客户数 | count(distinct case when entry_type='账单' then customer_code end) | 计数 |
| 在单合同数 | count(distinct case when entry_type='账单' then contract_no end) | 计数 |

**口径声明**：
- 应收余额 = 该维度成员**期内**账单合计 − 期内回款合计。无时间维度的报表（客户应收榜、
  合同台账）里它就是累计账单−累计回款，符合任务书语义；**SPEC 简化声明：该指标不用于
  时间维度报表**（跨月滚存余额需要窗口/累计语义，超出引擎"维度×指标聚合"能力）。
- 毛利 = 账单 − 人力成本（**简化口径**：不含税费、不含自有人员成本）。
- 外派人数在时间报表里=当月在册人数（distinct 员工），全期报表里=期内曾外派人数
  （distinct 去重）——聚合语义的自然结果，SPEC 预先声明。
- 账单行无交付组 → 交付组侧指标（外派人数/人力成本/人均人力成本）在交付组维度上
  只由在册行贡献；收入侧在交付组维度恒为 0，因此**交付组排行不用收入类指标**
  （用人均人力成本替代人均产值）。

---

## 6. 报表（6 张，定义以附录 dashboard.yml 为准）

| key | 标题 | 维度 | 时间 | 指标 | filters |
|---|---|---|---|---|---|
| monthly_kpi | 月度经营总览 | 月份 | 月份为维度 | 服务费收入/人力成本/毛利/毛利率/回款额/回款率/外派人数/人均产值/在单客户数 | — |
| bu_month | 事业部月报 | 事业部 | ×月份 | 服务费收入/毛利/毛利率/外派人数 | 行业 |
| group_rank | 交付组排行 | 交付组 | 无时间 | 外派人数/人力成本/人均人力成本 | 事业部 |
| customer_ar | 客户应收榜 | 客户 | 无时间 | 服务费收入/回款额/应收余额/在单合同数 | 行业, 客户级别 |
| industry_month | 行业月报 | 行业 | ×月份 | 服务费收入/毛利/外派人数 | 客户级别 |
| contract_ledger | 合同台账 | 合同 | 无时间 | 服务费收入/回款额/应收余额/外派人数 | — |

全部时间报表 `full_period_only: true`——本场景 12 个月全是完整月，该参数**不影响答案行集**。

**答案行集（密封答案的分组定义，SQL GROUP BY 语义，含 NULL 组）**：

| 报表 | 行数 | 说明 |
|---|---|---|
| monthly_kpi | 12 | 每完整月一行 |
| bu_month | 42 | 3 事业部 × 12 月 = 36 + **NULL 事业部组 6 行**（幽灵在册 5 个月 {2025-10, 2025-12, 2026-02, 2026-05, 2026-07} ∪ 幽灵回款 {2025-12, 2026-04}；该组收入=0、毛利为负、毛利率/回款率=NULL） |
| group_rank | 7 | 6 交付组 + **NULL 交付组组**（账单/回款行落此：外派人数=0、人力成本=0、人均人力成本=NULL） |
| customer_ar | 25 | 24 客户 + **NULL 客户组**（幽灵回款 HT-8888 落此：应收余额=−回款额，为负） |
| industry_month | 66 | （金融/互联网/制造/零售/文体）× 12 = 60 + **NULL 行业组 6 行**（同 bu_month 的幽灵月份；文体=混沌 H8 客户，全年有账单） |
| contract_ledger | 40 | 38 份有台账活动的合同 + **幽灵合同 HT-9999 / HT-8888 各自成组**（合同维度=主流水原始列 contract_no，幽灵键是真实值、不落 NULL 组：HT-9999 组收入=0、外派人数=5、毛利为负；HT-8888 组回款>0、应收为负）；2 份未来合同无台账活动 → **确定性缺席** |

**关于"客户应收榜按应收余额降序"**：报表展示排序属引擎/门户行为（能力边界），
**不进密封答案**；密封答案一律按 §8 排序规则（维度值升序）。
**引擎报表若在展示层隐藏全零组/NULL 组，对账以 marts 层 SQL 语义（本节定义）为准。**

---

## 7. 混沌条款

### 7.1 H 类：已注入数据内的脏与异常（基线数据自带，答案已计入其预期处理）

| # | 注入 | 行数 | 分布 | 预期处理（契约裁决） | 对答案的影响 |
|---|---|---|---|---|---|
| H1 | 账单超出合同止月 | 8 | 4 份提前截止合同，止月+1、+2 各一单 | **契约不可表达跨源业务规则**（字段契约无跨文件校验）→ 行正常入账；引擎能否提示=**能力缺口观察点**，非断言 | 全额计入（当月收入无对应在册成本，毛利抬升是确定性结果） |
| H2 | 账单早于合同起月 | 2 | 2 份合同起月前一月 | 同 H1（提前开票） | 全额计入 |
| H3 | 花名册幽灵合同 HT-9999 | 5 | 专属员工 EMP99001~99005，各 1 个月，分布见 §6 | 合同 join null_match **黄灯清单**必须出现 HT-9999；行保留，事业部/客户/行业/级别全 NULL | 人力成本与外派人数计入 **NULL 组**；交付组维度上落真实交付组 |
| H4 | 回款幽灵合同 HT-8888 | 2 | 2025-12、2026-04 | 同上，黄灯清单出现 HT-8888 | 回款额计入 **NULL 组**（客户/合同/行业/事业部的 NULL 行应收为负） |
| H5 | 账单金额千分位（`"1,234,500.00"`） | 6 | 6 个不同月份 | **契约裁决：类型转换失败**（引擎未声明千分位解析原语，v0.3 T3 先例同）→ 金额 NULL → 收入不计 | 收入不计；在单合同数/在单客户数照计；无对应回款（§1.5） |
| H6 | 账单合同号首尾空格 | 8 | 8 个不同月份 | `strip_strings` 清洗后精确匹配，**正常入账** | 全额计入（清洗链路考察点） |
| H7a | 花名册·月薪资成本缺失 | 30 | 散布 | `missing: default 0` 补 0，行不丢 | 该行成本贡献 0；外派人数照计 |
| H7b | 花名册·岗位缺失 | 12 | 散布 | `missing: default 未分类` | 岗位非维度，无报表影响（契约考察点） |
| H8 | 客户行业越枚举 `"文体"` | 1 家客户 | 该客户全年有账单 | enum 黄灯，行保留 | 行业月报多出"文体"组（12 行，正常收入） |
| H9 | 客户级别越枚举 `"S级"` | 1 家客户 | 该客户全年有账单 | enum 黄灯，行保留 | 无直接报表影响；作为 filters 值可被筛选（白名单考察点） |
| H10 | 回款金额 = −500（冲销） | 1 | 某正常合同某月 | range [0,100000000] 黄灯，行保留 | 回款额 **−500** 如实进入合计 |
| H11 | 回款双文件（202607 旧 + 202608 新） | — | mtime 旧<新 | 新文件胜出；旧文件 multi_match 黄灯留痕、不落 raw | 答案只认 202608 全量（=全部回款数据） |
| H12 | 2 份未来合同零台账活动 | — | 起月 2026-10/11 | 维表有、流水无 | 合同台账**确定性缺席**（分组语义），任何报表不出现 |
| H13 | 黄灯基线：账单/回款行交付组编码为空 | （结构性） | 全部账单/回款行 | 交付组 join null_match **预期基线 warn**（空键），不拦批 | NULL 交付组组 |

**生成保证（可断言）**：合同号/客户编码/组编码/事业部编码唯一；HT-9999/HT-8888 绝不在
合同表；合同→客户引用全有效；正常账单金额=当月该合同在册人数×月服务费（自洽）；
千分位行与空格行、幽灵行互不重叠。

### 7.2 B 类：破坏性注入（仅 TESTPLAN 副本用例，基线数据不含，无数字答案）

红灯族：B1 交付组.xlsx 重复组编码（fanout red → dbt error，build 失败）、
B2 合同.xlsx 重复合同号（unique 恒 red：ingest red + dbt error 双层，设计 §7.2）、
B3 客户.xlsx 表头改名（header_changed red）、B4 事业部.xlsx 清空（empty_file red）、
B5 月度账单改名/删除（file_missing red，含"彻底改名两 pattern 全不命中"变体）。
装配族：B6 metrics 引用不存在列（ConfigError）、B7 dashboard 引用未知指标/维度（ConfigError）。
查询族：B8 维度名非法必须报错 / 维度值非法静默回退 / 注入串不得进 SQL（P-08、D14、§4.3）。
阈值族：B9 在月度账单追加 4 行千分位使 bills 源 type_coerce_ratio 破 0.5% → 黄灯升档留痕。
完整清单与步骤见 `../TESTPLAN.md`。

---

## 8. 密封标准答案（expected/answer.json）

- **独立性**：答案由生成器内**纯 pandas/Decimal 独立重算**（不复用引擎任何代码），
  从"契约处理后的真相"出发：H6 去空格、H7 补默认、H5 置 NULL、H3/H4 幽灵合同匹空、
  H8/H9/H10 黄灯行保留——与 §7.1 契约裁决逐条对应。
- **结构**：`{"<report_key>": {"columns": [维度列, 指标列...], "rows": [{列: 值}, ...]}}`，
  六张报表齐备，行集=§6 表（全维度值全月份）。
- **排序**：时间升序；同月内按维度值字符串升序，**NULL 组恒排最后**；无时间报表按
  维度值升序、NULL 最后。
- **数值**：金额 round 2、比率 round 4、计数为整数；分母为 0 → null；
  null 一律 `null`。舍入用 Decimal ROUND_HALF_UP replicate SQL `round(x, n)`
  （先派生列逐行口径、再求和、再按指标定义舍入）。
- **密封**：`expected/manifest.sha256` 记录 answer.json 的 SHA256；评审前重跑
  生成器必须得到同一哈希（固定 seed，逐字节可复现）。
- 答案中不含任何"脏行明细"——脏行的预期处置**只**通过它对组指标的贡献体现；
  脏行清单本身（黄灯名单、留痕）是行为断言，归 TESTPLAN。

---

## 9. 规模摘要（生成器打印值为权威）

- 数据源 8 个（+1 诱饵文件）；12 个完整月（2025-09 ~ 2026-08）。
- 流水级行数 ≥ 10 万（花名册 ≈ 12.2 万 + 账单 ≈ 420 + 回款 ≈ 360；台账 ≈ 12.3 万）。
- 维度 7、指标 12、报表 6；密封答案 ≈ 192 行。
- 混沌：H 类 13 条（约 75 个脏行/异常对象），B 类 9 族破坏性用例。

## 10. 简化口径与能力边界声明（命题方自首清单）

1. 单宽表架构：账单/回款/在册三类事实以经营台账形式统一进一张宽表（设计 §3.2 一实例
   一宽表的必然结论）；账单按任务书为汇总粒度"直接给数"，流水级压力由在册表承担。
2. 应收余额不做跨月滚存（时间报表不含该指标）；毛利不含税费。
3. 签约事业部（合同侧）为收入/毛利归属口径；交付组侧只看人力指标。
4. 报表排序不进答案；全零组/NULL 组按 SQL 语义保留在答案中；未来合同缺席是确定性结论。
5. customers join 的左列来自 contracts join（有序 join 依赖，设计 §3.2"有序左联"）。
   若引擎不支持 join-on-joined-column，装配会报左列不存在——**这是引擎能力缺口，不是
   命题错误**：测试 Agent 如实记录现象，评审 Agent 按"SPEC 要求 vs 引擎实际"裁判。
6. 千分位按"类型转换失败"裁决（引擎若选择解析千分位为合法数值，属超预期宽容，
   评审按"答案以契约裁决为准 + 实际行为如实记录"处理，不得回改答案）。

---

## 附录 A：五配置装配基线（测试 Agent 照此写入 instances/hro/）

> 语义内容（patterns/契约/expr/指标报表定义）必须与本基线一致；注释与格式可自定。
> instance.yml：

```yaml
name: hro
title: 睿才人力
inbox: data/inbox
database: ../../../data/warehouse/hro.duckdb
tz: Asia/Shanghai
```

> sources.yml（8 源；事实源 problems 六件套，档案源三件）：

```yaml
version: 1
sources:
  - name: hro_ledger
    title: 经营台账
    discover: {patterns: ["经营台账*.csv", "hro_ledger*.csv"], encodings: [utf-8-sig, gbk]}
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 事项类型,   map: entry_type,   type: string,  required: true, enum: [账单, 回款, 在册], level: yellow}
      - {cn: 单据号,     map: doc_no,       type: string,  required: true, unique: true}
      - {cn: 单据月份,   map: doc_month,    type: date,    required: true}
      - {cn: 合同号,     map: contract_no,  type: string,  required: true}
      - {cn: 交付组编码, map: group_code,   type: string}
      - {cn: 员工编号,   map: employee_no,  type: string}
      - {cn: 姓名,       map: emp_name,     type: string}
      - {cn: 岗位,       map: position,     type: string,  missing: default, default: 未分类}
      - {cn: 月薪资成本, map: salary_cost,  type: decimal, missing: default, default: 0, range: [0, 100000], level: yellow}
      - {cn: 金额,       map: amount,       type: decimal}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red
      row_drop_ratio: {max: 0.01, level: yellow}
      type_coerce_ratio: {max: 0.005, level: yellow}

  - name: business_units
    title: 事业部
    discover: {patterns: ["事业部*.xlsx"], encodings: [utf-8-sig]}
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 事业部编码,   map: bu_code,       type: string, required: true, unique: true}
      - {cn: 事业部名称,   map: bu_name,       type: string}
      - {cn: 事业部负责人, map: bu_owner,      type: string}
    problems: {file_missing: red, header_changed: red, empty_file: red}

  - name: delivery_groups
    title: 交付组
    discover: {patterns: ["交付组*.xlsx"], encodings: [utf-8-sig]}
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 组编码,         map: group_code, type: string, required: true, unique: true}
      - {cn: 组名称,         map: group_name, type: string}
      - {cn: 所属事业部编码, map: bu_code,    type: string, required: true}
    problems: {file_missing: red, header_changed: red, empty_file: red}

  - name: customers
    title: 客户
    discover: {patterns: ["客户*.xlsx"], encodings: [utf-8-sig]}
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 客户编码, map: customer_code,  type: string, required: true, unique: true}
      - {cn: 客户名称, map: customer_name,  type: string}
      - {cn: 行业,     map: industry,       type: string, enum: [金融, 互联网, 制造, 零售], level: yellow}
      - {cn: 客户级别, map: customer_level, type: string, enum: [A, B, C], level: yellow}
    problems: {file_missing: red, header_changed: red, empty_file: red}

  - name: contracts
    title: 合同
    discover: {patterns: ["合同*.xlsx"], encodings: [utf-8-sig]}
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 合同号,       map: contract_no,   type: string,  required: true, unique: true}
      - {cn: 客户编码,     map: customer_code, type: string,  required: true}
      - {cn: 签约事业部编码, map: bu_code,     type: string,  required: true}
      - {cn: 签约事业部名称, map: bu_name,     type: string}
      - {cn: 月服务费,     map: monthly_fee,   type: decimal, required: true, range: [1000, 100000], level: yellow}
      - {cn: 开始月,       map: start_month,   type: string,  required: true, format: "^\\d{4}-\\d{2}$", level: yellow}
      - {cn: 结束月,       map: end_month,     type: string,  required: true, format: "^\\d{4}-\\d{2}$", level: yellow}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red
      row_drop_ratio: {max: 0.01, level: yellow}
      type_coerce_ratio: {max: 0.005, level: yellow}

  - name: roster
    title: 外派花名册（员工×月份 在册表）
    discover: {patterns: ["外派花名册*.xlsx"], encodings: [utf-8-sig]}
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 员工编号,   map: employee_no,  type: string, required: true}
      - {cn: 姓名,       map: emp_name,     type: string}
      - {cn: 月份,       map: doc_month,    type: date,   required: true}
      - {cn: 交付组编码, map: group_code,   type: string, required: true}
      - {cn: 合同号,     map: contract_no,  type: string, required: true}
      - {cn: 岗位,       map: position,     type: string, missing: default, default: 未分类}
      - {cn: 月薪资成本, map: salary_cost,  type: decimal, missing: default, default: 0, range: [0, 100000], level: yellow}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red
      row_drop_ratio: {max: 0.01, level: yellow}
      type_coerce_ratio: {max: 0.005, level: yellow}

  - name: bills
    title: 月度账单
    discover: {patterns: ["月度账单*.csv"], encodings: [utf-8-sig, gbk]}
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 月份,     map: doc_month,    type: date,   required: true}
      - {cn: 合同号,   map: contract_no,  type: string, required: true}
      - {cn: 账单金额, map: amount,       type: decimal, range: [0, 100000000], level: yellow}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red
      row_drop_ratio: {max: 0.01, level: yellow}
      type_coerce_ratio: {max: 0.005, level: yellow}

  - name: payments
    title: 回款记录
    discover: {patterns: ["回款记录*.csv"], encodings: [utf-8-sig, gbk]}   # 双文件命中→mtime 最新胜出（N-01）
    clean: [trim_columns, strip_strings]
    fields:
      - {cn: 月份,     map: doc_month,    type: date,   required: true}
      - {cn: 合同号,   map: contract_no,  type: string, required: true}
      - {cn: 回款金额, map: amount,       type: decimal, range: [0, 100000000], level: yellow}
    problems:
      file_missing: red
      header_changed: red
      empty_file: red
      empty_after_clean: red
      row_drop_ratio: {max: 0.01, level: yellow}
      type_coerce_ratio: {max: 0.005, level: yellow}
```

> wide.yml：

```yaml
version: 1
wide:
  name: wide_hro
  main: hro_ledger
  joins:
    - table: contracts
      keys: {left: contract_no, right: contract_no}
      how: left
      columns: [customer_code, bu_name, monthly_fee, start_month, end_month]
      contract: {fanout: red, null_match: yellow, orphan_right: ignore}
      # 幽灵合同 HT-9999/HT-8888 → 黄灯清单主考察点
    - table: customers
      keys: {left: customer_code, right: customer_code}   # 左列来自 contracts join——有序 join 依赖（设计 §3.2）
      how: left
      columns: [customer_name, industry, customer_level]
      contract: {fanout: red, null_match: yellow, orphan_right: ignore}
    - table: delivery_groups
      keys: {left: group_code, right: group_code}
      how: left
      columns: [group_name]
      contract: {fanout: red, null_match: yellow, orphan_right: ignore}
      # 黄灯基线：账单/回款行交付组编码为空属预期
  derived:
    - {name: bill_amt,  expr: "case when entry_type = '账单' then coalesce(amount, 0) else 0 end"}
    - {name: pay_amt,   expr: "case when entry_type = '回款' then coalesce(amount, 0) else 0 end"}
    - {name: cost_amt,  expr: "case when entry_type = '在册' then coalesce(salary_cost, 0) else 0 end"}
    - {name: gross_amt, expr: "case when entry_type = '账单' then coalesce(amount, 0) when entry_type = '在册' then -coalesce(salary_cost, 0) else 0 end"}
  drop: [_source_file, _loaded_at]
```

> dimensions.yml：

```yaml
version: 1
dimensions:
  - {name: 月份,     column: doc_month,     type: time, grain: month}
  - {name: 事业部,   column: bu_name,       type: category}
  - {name: 交付组,   column: group_name,    type: category}
  - {name: 客户,     column: customer_name, type: category}
  - {name: 行业,     column: industry,      type: category}
  - {name: 客户级别, column: customer_level, type: category}
  - {name: 合同,     column: contract_no,   type: category}
```

> metrics.yml：

```yaml
version: 1
metrics:
  - {name: 服务费收入,   expr: "sum(bill_amt)"}
  - {name: 回款额,       expr: "sum(pay_amt)"}
  - {name: 回款率,       expr: "round(sum(pay_amt) / nullif(sum(bill_amt), 0), 4)", format: percent}
  - {name: 应收余额,     expr: "sum(bill_amt) - sum(pay_amt)"}
  - {name: 人力成本,     expr: "sum(cost_amt)"}
  - {name: 毛利,         expr: "sum(gross_amt)"}
  - {name: 毛利率,       expr: "round(sum(gross_amt) / nullif(sum(bill_amt), 0), 4)", format: percent}
  - {name: 外派人数,     expr: "count(distinct case when entry_type = '在册' then employee_no end)"}
  - {name: 人均产值,     expr: "round(sum(bill_amt) / nullif(count(distinct case when entry_type = '在册' then employee_no end), 0), 2)"}
  - {name: 人均人力成本, expr: "round(sum(cost_amt) / nullif(count(distinct case when entry_type = '在册' then employee_no end), 0), 2)"}
  - {name: 在单客户数,   expr: "count(distinct case when entry_type = '账单' then customer_code end)"}
  - {name: 在单合同数,   expr: "count(distinct case when entry_type = '账单' then contract_no end)"}
```

> dashboard.yml：

```yaml
version: 1
reports:
  - key: monthly_kpi
    title: 月度经营总览
    dimension: 月份
    metrics: [服务费收入, 人力成本, 毛利, 毛利率, 回款额, 回款率, 外派人数, 人均产值, 在单客户数]
    chart: bar_line
    full_period_only: true
  - key: bu_month
    title: 事业部月报
    dimension: 事业部
    time_dim: 月份
    metrics: [服务费收入, 毛利, 毛利率, 外派人数]
    filters: [行业]
    chart: stack_bar
    full_period_only: true
  - key: group_rank
    title: 交付组排行
    dimension: 交付组
    metrics: [外派人数, 人力成本, 人均人力成本]
    filters: [事业部]
    chart: hbar
  - key: customer_ar
    title: 客户应收榜
    dimension: 客户
    metrics: [服务费收入, 回款额, 应收余额, 在单合同数]
    filters: [行业, 客户级别]
    chart: hbar
  - key: industry_month
    title: 行业月报
    dimension: 行业
    time_dim: 月份
    metrics: [服务费收入, 毛利, 外派人数]
    filters: [客户级别]
    chart: stack_bar
    full_period_only: true
  - key: contract_ledger
    title: 合同台账
    dimension: 合同
    metrics: [服务费收入, 回款额, 应收余额, 外派人数]
    chart: hbar
```

