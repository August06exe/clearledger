-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(order_id as varchar)) as order_id,
    cast(order_date as date) as order_date,
    trim(cast(customer_id as varchar)) as customer_id,
    trim(cast(product_id as varchar)) as product_id,
    cast(quantity as bigint) as quantity,
    cast(unit_price as decimal(18, 4)) as unit_price,
    coalesce(cast(discount_rate as decimal(18, 4)), 0) as discount_rate,
    cast(amount as decimal(18, 4)) as amount
from {{ source('raw', 'sales_transactions') }}
where order_id is not null
  and order_date is not null
  and customer_id is not null
  and product_id is not null
  and quantity is not null
  and amount is not null
