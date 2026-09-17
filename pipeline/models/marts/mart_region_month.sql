-- 区域经营月历：月 × 区域
-- 费用列 = 该区域当月分摊费用（事业部费用直接归属 + 总部职能按收入占比分摊）
with base as (
    select
        date_trunc('month', e.order_date) as month,
        e.region_code,
        e.region_name,
        sum(e.net_amount) as revenue,
        sum(e.gross_profit) as gross_profit
    from {{ ref('int_sales_enriched') }} e
    group by 1, 2, 3
),
alloc as (
    select
        month,
        region_code,
        sum(allocated_amount) as allocated_expense
    from {{ ref('int_expense_alloc') }}
    group by 1, 2
)
select
    base.month,
    base.region_code,
    base.region_name,
    base.revenue,
    base.gross_profit,
    round(base.gross_profit / nullif(base.revenue, 0), 4) as gross_margin,
    coalesce(alloc.allocated_expense, 0) as allocated_expense,
    base.gross_profit - coalesce(alloc.allocated_expense, 0) as net_profit,
    round(base.revenue / nullif(lag(base.revenue) over (partition by base.region_code order by base.month), 0) - 1, 4) as revenue_mom
from base
left join alloc
    on base.month = alloc.month
   and base.region_code = alloc.region_code
