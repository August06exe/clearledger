-- 客户经营汇总（LTM = 最近 12 个"完整月"，截至最新完整月；部分月不计入）
with bounds as (
    select case
        when date_trunc('month', max(order_date)) >= date_trunc('month', current_date)
            then date_trunc('month', current_date) - interval '12' month
        else date_trunc('month', max(order_date)) - interval '11' month
    end as ltm_start
    from {{ ref('int_sales_enriched') }}
),
agg as (
    select
        e.customer_id,
        count(*) as order_cnt,
        sum(e.net_amount) as ltm_revenue,
        sum(e.gross_profit) as ltm_gross_profit,
        max(e.order_date) as last_order_date
    from {{ ref('int_sales_enriched') }} e
    cross join bounds b
    where date_trunc('month', e.order_date) >= b.ltm_start
      and date_trunc('month', e.order_date) < date_trunc('month', current_date)
    group by 1
)
select
    c.customer_id,
    c.customer_name,
    c.industry,
    c.customer_level,
    c.region_code,
    c.region_name,
    c.status,
    coalesce(a.order_cnt, 0) as order_cnt,
    coalesce(a.ltm_revenue, 0) as ltm_revenue,
    coalesce(a.ltm_gross_profit, 0) as ltm_gross_profit,
    round(coalesce(a.ltm_gross_profit, 0) / nullif(a.ltm_revenue, 0), 4) as gross_margin,
    a.last_order_date
from {{ ref('stg_customers') }} c
left join agg a on c.customer_id = a.customer_id
