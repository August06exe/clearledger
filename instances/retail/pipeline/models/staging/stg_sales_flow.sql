-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(flow_no as varchar)) as flow_no,
    cast(sale_date as date) as sale_date,
    trim(cast(store_code as varchar)) as store_code,
    trim(cast(product_code as varchar)) as product_code,
    trim(cast(channel as varchar)) as channel,
    cast(quantity as bigint) as quantity,
    cast(unit_price as decimal(18, 4)) as unit_price,
    coalesce(cast(discount_rate as decimal(18, 4)), 0) as discount_rate
from {{ source('raw', 'sales_flow') }}
where flow_no is not null
  and sale_date is not null
  and store_code is not null
  and product_code is not null
  and quantity is not null
