-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(return_no as varchar)) as return_no,
    cast(return_date as date) as return_date,
    trim(cast(store_code as varchar)) as store_code,
    trim(cast(product_code as varchar)) as product_code,
    trim(cast(supplier_code as varchar)) as supplier_code,
    cast(quantity as bigint) as quantity,
    cast(unit_price as decimal(18, 4)) as unit_price
from {{ source('raw', 'purchase_returns') }}
where return_no is not null
  and return_date is not null
  and store_code is not null
  and product_code is not null
  and quantity is not null
