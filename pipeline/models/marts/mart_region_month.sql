-- 区域经营月历：月 × 区域
-- 月 × 区域 骨架保证：某区域某月零销售也成行（收入记 0），
-- 环比永远基于上一日历月；费用列 = 该区域当月分摊费用。
with month_spine as (
    -- 月骨架 = 费用月份 ∪ 销售月份（费用是完整月度台账，可兜住整月零销售的极端情况）
    select distinct date_trunc('month', expense_date) as month
    from {{ ref('stg_expenses') }}
    union
    select distinct date_trunc('month', order_date) as month
    from {{ ref('int_sales_enriched') }}
),
regions as (
    select distinct region_code
    from {{ ref('stg_customers') }}
    where region_code is not null
),
grid as (
    select m.month, r.region_code
    from month_spine m
    cross join regions r
),
region_names as (
    -- 区域名取自客户维表（不依赖销售数据，从未有销售的区域也有名字）
    select region_code, max(region_name) as region_name
    from {{ ref('stg_customers') }}
    where region_code is not null
    group by 1
),
sales as (
    select
        date_trunc('month', order_date) as month,
        region_code,
        sum(net_amount) as revenue,
        sum(gross_profit) as gross_profit
    from {{ ref('int_sales_enriched') }}
    group by 1, 2
),
alloc as (
    select
        month,
        region_code,
        sum(allocated_amount) as allocated_expense
    from {{ ref('int_expense_alloc') }}
    group by 1, 2
),
base as (
    select
        g.month,
        g.region_code,
        coalesce(s.revenue, 0) as revenue,
        coalesce(s.gross_profit, 0) as gross_profit,
        coalesce(a.allocated_expense, 0) as allocated_expense
    from grid g
    left join sales s
        on s.month = g.month and s.region_code = g.region_code
    left join alloc a
        on a.month = g.month and a.region_code = g.region_code
)
select
    b.month,
    b.region_code,
    rn.region_name,
    b.revenue,
    b.gross_profit,
    round(b.gross_profit / nullif(b.revenue, 0), 4) as gross_margin,
    b.allocated_expense,
    b.gross_profit - b.allocated_expense as net_profit,
    round(b.revenue / nullif(lag(b.revenue) over (partition by b.region_code order by b.month), 0) - 1, 4) as revenue_mom
from base b
left join region_names rn on rn.region_code = b.region_code
