-- 商品月度销售：月 × 品类 × 商品
select
    date_trunc('month', order_date) as month,
    category,
    product_id,
    product_name,
    sum(quantity) as quantity,
    sum(net_amount) as revenue,
    sum(gross_profit) as gross_profit
from {{ ref('int_sales_enriched') }}
group by 1, 2, 3, 4
