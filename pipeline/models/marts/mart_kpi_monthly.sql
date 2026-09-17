-- 公司级经营月历（指标口径的唯一报表层出处）
-- 口径：
--   收入 = Σ 折后金额；毛利 = Σ（折后 − 标准成本）；净利 = 毛利 − 分摊费用
--   环比基于"上一日历月"：月骨架保证无销售月份也成行（收入记 0），
--   因此环比永远不会"跳月"拿上上个月当分母。
with month_spine as (
    -- 月骨架 = 费用月份 ∪ 销售月份（费用是完整月度台账，可兜住整月零销售的极端情况）
    select distinct date_trunc('month', expense_date) as month
    from {{ ref('stg_expenses') }}
    union
    select distinct date_trunc('month', order_date) as month
    from {{ ref('int_sales_enriched') }}
),
rev as (
    select
        date_trunc('month', order_date) as month,
        sum(net_amount) as revenue,
        sum(cost_amount) as cost_amount,
        sum(gross_profit) as gross_profit
    from {{ ref('int_sales_enriched') }}
    group by 1
),
exp as (
    select month, sum(allocated_amount) as expense
    from {{ ref('int_expense_alloc') }}
    group by 1
),
base as (
    select
        s.month,
        coalesce(r.revenue, 0) as revenue,
        coalesce(r.cost_amount, 0) as cost_amount,
        coalesce(r.gross_profit, 0) as gross_profit,
        coalesce(e.expense, 0) as expense
    from month_spine s
    left join rev r on s.month = r.month
    left join exp e on s.month = e.month
)
select
    month,
    revenue,
    cost_amount,
    gross_profit,
    expense,
    gross_profit - expense as net_profit,
    round(gross_profit / nullif(revenue, 0), 4) as gross_margin,
    round((gross_profit - expense) / nullif(revenue, 0), 4) as net_margin,
    round(revenue / nullif(lag(revenue) over (order by month), 0) - 1, 4) as revenue_mom,
    round(gross_profit / nullif(lag(gross_profit) over (order by month), 0) - 1, 4) as gross_profit_mom,
    round((gross_profit - expense) / nullif(lag(gross_profit - expense) over (order by month), 0) - 1, 4) as net_profit_mom
from base
