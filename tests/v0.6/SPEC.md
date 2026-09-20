# SPEC — v0.6 验收场景圣经（测试实例 `_wb_r1`）

> **密封伴侣文档：测试 Agent 不读本文。** 测试 Agent 的唯一指令来源是 [TESTPLAN.md](TESTPLAN.md)；
> 本文供评审、判分者与修复者使用，包含播种清单的预期规则/级别/计数（答案相邻信息）。
> 命题依据：[设计-v0.5-配置工作台.md](../docs/设计-v0.5-配置工作台.md)（API 契约唯一出处）、
> [待确认与决策.md](../docs/待确认与决策.md) D15（数据契约三层）、现有账套配置写法（retail 形态）。
> 配置与数据的**唯一真相源**是 [generate.py](generate.py)（幂等生成器）；本文引用其常量，手改本文无效。

## 1. 实例总览

| 项 | 值 |
|---|---|
| 实例名 | `_wb_r1`（下划线前缀 = 测试副本约定，工作台可寻址、不出现在正式账套清单） |
| 域形态 | 零售进销存（镜像 `instances/retail/` 的契约词汇，规模最小化） |
| 目录 | `instances/_wb_r1/`（六份 yml + `data/inbox/` 五个 CSV） |
| 独立库 | `data/warehouse/_wb_r1.duckdb`（`data/` 不入 git；由三步链的 ingest 创建/全量覆盖） |
| 规模 | 5 个数据源、inbox 共 **93 数据行**（49+21+6+12+5），三步链秒级 |
| 灯色预期 | 三步链退出码全 0（播种违规全部 yellow 级，不触发红灯退出）；run 终态=成功；灯允许绿/黄（黄若出现来自 dbt 测试 warn 机制，与契约黄行是两条不同机制，皆非失败） |

数据流：`generate.py` → `semantic.ingest_run --instance _wb_r1` → `semantic.compile_dbt --instance _wb_r1` → dbt build（命令全文见 TESTPLAN §2）。

## 2. 六份 YAML 配置全文

与 `generate.py` 内常量逐字节一致（重生成即恢复）。

### 2.1 instance.yml
```yaml
name: _wb_r1
title: 工作台测试账套R1（零售进销存形态）
inbox: data/inbox
database: ../../../data/warehouse/_wb_r1.duckdb
tz: Asia/Shanghai
```

### 2.2 sources.yml（入口档案 + 字段契约）
五个源：`fact_ledger`（主表，进销存台账）、`stock_snapshot`（库存快照）、`stores`（门店）、`products`（商品）、`suppliers`（供应商）。全部 CSV 单文件命中（patterns 见下），`clean: [trim_columns, strip_strings]`，problems 四条款（file_missing / header_changed / empty_file / empty_after_clean）全部 `red`（基线数据下均不触发）。

<details><summary>全文（点开）</summary>

```yaml
version: 1
sources:
  - name: fact_ledger            # 台账_*.csv
    fields:
      - {cn: 事项类型, map: entry_type,    type: string,  required: true, level: yellow, enum: [销售, 采购, 采购退货, 期末库存]}
      - {cn: 单据号,   map: doc_no,        type: string,  required: true, level: yellow}
      - {cn: 单据日期, map: doc_date,      type: date,    required: true, level: yellow}
      - {cn: 门店编码, map: store_code,    type: string,  required: true, level: yellow}
      - {cn: 商品编码, map: product_code,  type: string,  required: true, level: yellow}
      - {cn: 供应商编码, map: supplier_code, type: string}
      - {cn: 渠道,     map: channel,       type: string,  enum: [门店, 电商], level: yellow}
      - {cn: 数量,     map: quantity,      type: integer, range: [1, 999], level: yellow}
      - {cn: 单价,     map: unit_price,    type: decimal, level: yellow}
      - {cn: 折扣率,   map: discount_rate, type: decimal, range: [0, 1], level: yellow, missing: default, default: 0}
      - {cn: 期末数量, map: ending_qty,    type: integer, range: [0, 1000000], level: yellow}
  - name: stock_snapshot         # 库存快照_*.csv
    fields:
      - {cn: 快照月份, map: snap_month,   type: string}
      - {cn: 快照日期, map: snap_date,    type: date,    required: true, level: yellow}
      - {cn: 门店编码, map: store_code,   type: string,  required: true, level: yellow}
      - {cn: 商品编码, map: product_code, type: string,  required: true, level: yellow}
      - {cn: 期末数量, map: ending_qty,   type: integer, required: true, level: yellow, range: [0, 100000]}
  - name: stores                 # 门店_*.csv（门店编码 required，有意不声明 unique——SCD 形态，重复键走 join 扇出语义）
    fields:
      - {cn: 门店编码, map: store_code,  type: string, required: true, level: yellow}
      - {cn: 门店名称, map: store_name,  type: string}
      - {cn: 城市,     map: city,        type: string}
      - {cn: 大区,     map: region_name, type: string, enum: [华东, 华北, 华南], level: yellow}
      - {cn: 开业日期, map: open_date,   type: date}
  - name: products               # 商品_*.csv
    fields:
      - {cn: 商品编码, map: product_code, type: string, required: true, level: yellow}
      - {cn: 商品名称, map: product_name, type: string}
      - {cn: 品类,     map: category,     type: string, enum: [食品, 百货, 日化], level: yellow}
      - {cn: 单位,     map: unit,         type: string}
      - {cn: 标准成本, map: std_cost,      type: decimal, level: yellow}
  - name: suppliers              # 供应商_*.csv（零违规源：验证投影按源完备而非全有违规）
    fields:
      - {cn: 供应商编码, map: supplier_code, type: string, required: true, level: yellow}
      - {cn: 供应商名称, map: supplier_name, type: string}
      - {cn: 结算方式,   map: settle_type,   type: string, enum: [月结30, 月结60, 现结], level: yellow}
```
</details>

### 2.3 wide.yml（关联 + 派生列）
```yaml
version: 1
wide:
  name: wide_ledger
  main: fact_ledger
  joins:                          # 三张标签表全部 left join，契约三处（V6/V7 播种见 §4）
    - table: stores
      keys: {left: store_code, right: store_code}
      how: left
      columns: [store_name, city, region_name]
      contract: {fanout: yellow, null_match: yellow, orphan_right: ignore}
    - table: products
      keys: {left: product_code, right: product_code}
      how: left
      columns: [product_name, category, std_cost]
      contract: {fanout: yellow, null_match: yellow, orphan_right: ignore}
    - table: suppliers
      keys: {left: supplier_code, right: supplier_code}
      how: left
      columns: [supplier_name]
      contract: {fanout: yellow, null_match: yellow, orphan_right: ignore}
  derived:
    - {name: sales_net,    expr: "case when entry_type = '销售' then round(quantity * unit_price * (1 - discount_rate), 2) else 0 end", desc: "销售行折后金额 = 数量×单价×(1−折扣率)"}
    - {name: sales_cost,   expr: "case when entry_type = '销售' then round(quantity * std_cost, 2) else 0 end", desc: "销售行成本 = 数量×标准成本"}
    - {name: gross_profit, expr: "case when entry_type = '销售' then round(quantity * unit_price * (1 - discount_rate) - quantity * std_cost, 2) else 0 end", desc: "销售行毛利 = 折后金额 − 成本"}
    - {name: ecomm_net,    expr: "case when entry_type = '销售' and channel = '电商' then round(quantity * unit_price * (1 - discount_rate), 2) else 0 end", desc: "电商渠道销售行折后金额"}
    - {name: purchase_amt, expr: "case when entry_type = '采购' then round(quantity * unit_price, 2) else 0 end", desc: "采购行金额 = 数量×采购单价"}
    - {name: stock_qty,    expr: "case when entry_type = '期末库存' then coalesce(ending_qty, 0) else 0 end", desc: "期末库存行数量"}
  drop: [_source_file, _loaded_at]
```

### 2.4 dimensions.yml（8 个维度；`商品` 有意不被任何报表引用）
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
  - {name: 商品,   column: product_code,  type: category}
```

### 2.5 metrics.yml（7 个指标；`电商销售占比` 有意不被任何报表引用）
```yaml
version: 1
metrics:
  - {name: 销售额,       expr: "sum(sales_net)", desc: "折后销售合计 = 数量×单价×(1−折扣率)，仅销售行"}
  - {name: 销售成本,     expr: "sum(sales_cost)", desc: "数量×商品标准成本 合计，仅销售行"}
  - {name: 毛利,         expr: "sum(gross_profit)", desc: "销售额 − 销售成本"}
  - {name: 毛利率,       expr: "round(sum(gross_profit) / nullif(sum(sales_net), 0), 4)", format: percent, desc: "毛利 ÷ 销售额；销售额为 0 时为空"}
  - {name: 采购额,       expr: "sum(purchase_amt)", desc: "采购行 数量×采购单价 合计"}
  - {name: 期末库存量,   expr: "sum(stock_qty)", desc: "期末库存行数量合计"}
  - {name: 电商销售占比, expr: "round(sum(ecomm_net) / nullif(sum(sales_net), 0), 4)", format: percent, desc: "电商渠道销售额 ÷ 总销售额"}
```

### 2.6 dashboard.yml（6 张报表；覆盖 dimension / time_dim / filters 三类引用）
```yaml
version: 1
reports:
  - key: monthly_kpi      # dimension=月份；metrics=[销售额,毛利,毛利率]
    title: 月度经营总览
    dimension: 月份
    metrics: [销售额, 毛利, 毛利率]
    chart: bar_line
    full_period_only: true
  - key: region_month     # dimension=大区, time_dim=月份, filters=[城市]；metrics=[销售额,毛利]
    title: 大区月报
    dimension: 大区
    time_dim: 月份
    metrics: [销售额, 毛利]
    filters: [城市]
    chart: stack_bar
    full_period_only: true
  - key: category_month   # dimension=品类, time_dim=月份；metrics=[销售额,销售成本,毛利率]
    title: 品类月报
    dimension: 品类
    time_dim: 月份
    metrics: [销售额, 销售成本, 毛利率]
    chart: stack_bar
    full_period_only: true
  - key: channel_month    # dimension=渠道, time_dim=月份；metrics=[销售额,毛利]
    title: 渠道月报
    dimension: 渠道
    time_dim: 月份
    metrics: [销售额, 毛利]
    chart: stack_bar
    full_period_only: true
  - key: store_rank       # dimension=门店, filters=[大区,城市]；metrics=[销售额,毛利,期末库存量]
    title: 门店排行
    dimension: 门店
    metrics: [销售额, 毛利, 期末库存量]
    filters: [大区, 城市]
    chart: hbar
  - key: supplier_rank    # dimension=供应商；metrics=[采购额]
    title: 供应商采购排行
    dimension: 供应商
    metrics: [采购额]
    chart: hbar
```

## 3. inbox CSV 文件形态

全部 utf-8-sig（BOM）+ LF。列序与 sources.yml 各源 `cn` 顺序逐列一致（`header_changed: red` 不许触发）。日期区间 2026-07-01 ~ 2026-08-31（两个完整月）。

| 文件（patterns 命中） | 列名 | 数据行数 |
|---|---|---|
| `台账_202608.csv`（台账_\*.csv） | 事项类型, 单据号, 单据日期, 门店编码, 商品编码, 供应商编码, 渠道, 数量, 单价, 折扣率, 期末数量 | 49 |
| `库存快照_202608.csv`（库存快照_\*.csv） | 快照月份, 快照日期, 门店编码, 商品编码, 期末数量 | 21 |
| `门店_202608.csv`（门店_\*.csv） | 门店编码, 门店名称, 城市, 大区, 开业日期 | 6 |
| `商品_202608.csv`（商品_\*.csv） | 商品编码, 商品名称, 品类, 单位, 标准成本 | 12 |
| `供应商_202608.csv`（供应商_\*.csv） | 供应商编码, 供应商名称, 结算方式 | 5 |

台账 49 行构成：销售 29（21 干净 + 3 行 S05 供应商回填 + 3 行 V1 + 1 行 V3 + 1 行 V4a）+ 采购 11（8 干净 + 2 行 V2 + 1 行 V4b）+ 采购退货 4 + 期末库存 5（期末数量回填，供应商/渠道/数量/单价/折扣率留空）。行内单据号唯一可 grep（`SZ-`/`PO-`/`RT-`/`QM-` 前缀）。

## 4. 故意播种的契约违规清单（数据层播种，配置本身合法）

违规行号 = **数据行号（不含表头）**，可用单据号 grep 定位。行彼此不相交（一行只触发一类违规，被剔行不参与任何下游计数）。

### 4.1 正向播种（预期产生契约行）

| id | 文件:行 | 播种值 | 触发契约 | 预期 rule | 预期 level | 预期 cnt | 下游效应 |
|---|---|---|---|---|---|---|---|
| V1 | 台账:26,27,28 | 渠道=`团购` | fact_ledger.channel enum [门店,电商] | enum | yellow | 3 | 行保留 |
| V2 | 台账:33 | 数量=`2000` | fact_ledger.quantity range [1,999] | range | yellow | 2 | 行保留（与 ：39 合计 cnt=2） |
| V2 | 台账:39 | 数量=`0` | 同上 | range | yellow | （并入上行） | 行保留 |
| V3 | 台账:14（SZ-2607-014） | 单价=`N/A` | fact_ledger.unit_price type decimal 不可强转 | type | yellow | 1 | **该行被剔**（假设 A3） |
| V4 | 台账:29（空单据号销售行） | 单据号=空 | fact_ledger.doc_no required | required | yellow | 2 | **该行被剔**（假设 A4；与 :40 合计 cnt=2） |
| V4 | 台账:40（空单据号采购行） | 单据号=空 | 同上 | required | yellow | （并入上行） | **该行被剔** |
| V6 | 台账（29 行） | 供应商编码=空的销售行 24 + 期末库存行 5 | wide_ledger×suppliers join null_match | null_match | yellow | 29 | 行保留、匹配为空 |
| V7 | 门店:5,6 | S05 两行（社区五店/社区五店二号） | wide_ledger×stores join 右键重复 fanout | fanout | yellow | 4 | 受影响台账左行=13,24,25,49 四行，**宽表物理扩 4 行**（假设 A9） |
| V8 | 库存快照:21 | 期末数量=`-5` | stock_snapshot.ending_qty range [0,100000] | range | yellow | 1 | 行保留 |
| V9 | 商品:12（FP009） | 品类=`生鲜` | products.category enum [食品,百货,日化] | enum | yellow | 1 | 行保留 |

**预期契约行合计：8 条 (source, field, rule, level, cnt) 投影** —— fact_ledger×4（channel/enum=3、doc_no/required=2、quantity/range=2、unit_price/type=1）、products×1（category/enum=1）、stock_snapshot×1（ending_qty/range=1）、wide_ledger×2（store_code/fanout=4、supplier_code/null_match=29）。全部 level=yellow（假设 A1）。

### 4.2 反向播种（预期**零**契约行——投影完备性的对照面）

| id | 播种 | 预期 |
|---|---|---|
| N1 | 折扣率空 ×6（台账:2,4,9,11,16,18） | `missing: default, default: 0` 补 0，**无契约行**（假设 A6）；下游金额按 0 折扣计算 |
| N2 | FP009（生鲜行）不被任何台账行引用 | `orphan_right: ignore`，**无契约行** |
| N3 | 期末库存行渠道/数量/单价为空、采购行供应商回填 | 空值跳过 enum/range（假设 A7），**无契约行** |
| N4 | 五文件齐全、表头逐列一致、无空文件；剔行 3/49 ≈ 6%（problems 未配置 row_drop_ratio 条款） | problems 类条款全不触发，**无 field="-" 行** |
| N5 | entry_type 全部合法、供应商 S05 行大区=华东、结算方式全合法 | 合法值不产生行 |

### 4.3 行数口径（W 类对数用，语义见假设 A5/A9）

| 口径 | 值 |
|---|---|
| 文件数据行 | 台账 49 / 快照 21 / 门店 6 / 商品 12 / 供应商 5（合计 93） |
| raw 各源表（镜像假设 A5） | 同文件行数 |
| 剔行（A3+A4） | 3 行（台账 :14、:29、:40）→ 保留 46 |
| 宽表 wide_ledger（A9） | 46 + 4（V7 扩行）= **50** |

## 5. 影响预览的推导规则（设计 §3.6，纯配置）

- `metrics`：指标 m → `reports[].metrics` 数组包含 m 的报表 key 列表，key 升序；未被引用 → `[]`。
- `dimensions`：维度 d → `dimension` + `time_dim` + `filters` 三处引用的报表 key 并集，key 升序；未被引用 → `[]`。
- 本配置的设计点：`电商销售占比` 与 `商品` 是刻意的未引用项（必须映射 `[]`）；`销售额` 被 5 张报表引用；`月份` 经 dimension+time_dim 两种槽位被 4 张报表引用；`城市`/`大区` 经 filters 槽位引用（`城市` ∈ region_month.filters 与 store_rank.filters）。
- 权威数值以密封区 `expected/answer.json` 的 `impact` 节为准（评审可按本节规则独立复推）。

## 6. 行为契约要点（B/MR 类案的依据索引）

| 条款（设计文档） | 内容 | 关联 Case |
|---|---|---|
| §3.2 | YAML 解析失败也 200（parsed_ok:false），看坏文件不许 500 | B-01 对照 |
| §3.3 | validate 三层校验（语法/映射/交叉），**零文件副作用（含 mtime）**；warnings 恒空数组 | B-01 |
| §3.3/3.4 | 校验不过 → 422 `{"ok":false,"errors":[...]}`，**绝不落盘**、不产生备份 | B-02 |
| §3.4 | 保存：校验→备份（`onboarding/config_history/<block>.prev.yml` 固定路径单份滚动）→临时文件原子 replace | B-03, MR-01 |
| §3.4 | affected_reports 仅 metrics/dashboard 块返回，其余块 `[]` | B-03（observed 记录） |
| §3.4 | rebuild=true 触发三步链，触发器标记 `"workbench"`；互斥冲突时保存仍成功 | B-06 |
| §2/§4 | 块白名单封闭；`permissions.yml` 不存在，请求也 404 | B-04 |
| §4.1 | 实例名 `^[A-Za-z0-9][A-Za-z0-9_\-]*$` + 解析后必须在 instances/ 之下；穿越一律 404、绝不落盘到 instances 之外 | B-05 |
| §6.1 | `_wb_*` 不出现在正式账套清单 | B-07 |
| §6.2 | 官方四账套任何文件不得被测试改动 | B-08 |
| §3.5 | pending 读最近 run 全部行，稳定投影六字段，按 (source,field,rule) 升序 | W-01, MR-03 |
| §6.4 | pending 投影 / save 后回读 / impact 同输入双跑逐字节一致（除已排除易变字段） | MR-01/03/04 |

## 7. 基线恢复配方

```bash
rm -rf instances/_wb_r1
.venv/Scripts/python.exe tests/v0.6/generate.py
.venv/Scripts/python.exe -m semantic.ingest_run  --instance _wb_r1
.venv/Scripts/python.exe -m semantic.compile_dbt --instance _wb_r1
(cd instances/_wb_r1/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors)
```

## 8. 独立口径假设（与 caliber.json 逐字同步；引擎分歧时归因指引）

- **A1** contract_report.level = 配置声明的级别字面量（yellow/red）；设计 §3.5 示例中的 "pending" 视为示意值。
- **A2** 软违规（enum/range/unique/null_match/fanout）记录不剔行。
- **A3** 类型不可强转 → 记 rule=type 且剔行。
- **A4** required 空值 → 记 rule=required 且剔行。
- **A5** raw 层为源文件镜像（手册红线"原始层只增不改"），raw 行数 = 文件数据行数。
- **A6** missing=default 补默认值、零契约行。
- **A7** 空值跳过 enum/range（retail 真实基线佐证：海量空供应商编码未产生枚举/范围行）。
- **A8** join 契约行 source=宽表名（wide_ledger），field=左表键列名。
- **A9** fanout 物理扩行：cnt=受影响左行数；宽表行数 = 保留主表行数 + 扩行数。

归因原则：**命题方不为对齐引擎而改答案**。词表分歧（rule/level 命名）→ spec↔engine 分歧归评审；计数分歧 → 对应假设条目；`rows.raw` → A5；`rows.wide_ledger` → A3/A4/A9；join 行归属 → A8。
