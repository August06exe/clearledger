-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(po_no as varchar)) as po_no,
    cast(po_date as date) as po_date,
    trim(cast(store_code as varchar)) as store_code,
    trim(cast(product_code as varchar)) as product_code,
    trim(cast(supplier_code as varchar)) as supplier_code,
    cast(quantity as bigint) as quantity,
    cast(unit_price as decimal(18, 4)) as unit_price
from {{ source('raw', 'purchase_orders') }}
where po_no is not null
  and po_date is not null
  and store_code is not null
  and product_code is not null
  and quantity is not null
