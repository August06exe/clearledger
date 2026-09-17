-- 公司级经营月历（指标口径的唯一报表层出处）
-- 口径：
--   收入 = Σ 折后金额
--   毛利 = Σ 毛利（折后 − 标准成本）
--   费用 = Σ 分摊到全部区域的费用
--   净利 = 毛利 − 费用
with rev as (
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
)
select
    rev.month,
    rev.revenue,
    rev.cost_amount,
    rev.gross_profit,
    coalesce(exp.expense, 0) as expense,
    rev.gross_profit - coalesce(exp.expense, 0) as net_profit,
    round(rev.gross_profit / nullif(rev.revenue, 0), 4) as gross_margin,
    round((rev.gross_profit - coalesce(exp.expense, 0)) / nullif(rev.revenue, 0), 4) as net_margin,
    round(rev.revenue / nullif(lag(rev.revenue) over (order by rev.month), 0) - 1, 4) as revenue_mom,
    round(rev.gross_profit / nullif(lag(rev.gross_profit) over (order by rev.month), 0) - 1, 4) as gross_profit_mom
from rev
left join exp on rev.month = exp.month
