
  
  create view "sales"."intermediate"."int_wide_sales__dbt_tmp" as (
    -- 生成物：宽表装配（sales_transactions + 2 张标签表左联 + 派生列）
select
    m.order_id,
    m.order_date,
    m.customer_id,
    m.product_id,
    m.quantity,
    m.unit_price,
    m.discount_rate,
    m.amount,
    d0.customer_name,
    d0.industry,
    d0.customer_level,
    d0.region_code,
    d0.region_name,
    d0.status,
    d1.product_name,
    d1.category,
    d1.std_cost,
    round(amount * (1 - discount_rate), 2) as net_amount,
    round(quantity * std_cost, 2) as cost_amount,
    round(amount * (1 - discount_rate) - quantity * std_cost, 2) as gross_profit
from "sales"."staging"."stg_sales_transactions" m
left join "sales"."staging"."stg_customers" d0
  on m.customer_id = d0.customer_id
left join "sales"."staging"."stg_products" d1
  on m.product_id = d1.product_id
  );
