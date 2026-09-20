-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(entry_type as varchar)) as entry_type,
    trim(cast(doc_no as varchar)) as doc_no,
    cast(doc_date as date) as doc_date,
    trim(cast(store_code as varchar)) as store_code,
    trim(cast(product_code as varchar)) as product_code,
    trim(cast(supplier_code as varchar)) as supplier_code,
    trim(cast(channel as varchar)) as channel,
    cast(quantity as bigint) as quantity,
    cast(unit_price as decimal(18, 4)) as unit_price,
    coalesce(cast(discount_rate as decimal(18, 4)), 0) as discount_rate,
    cast(ending_qty as bigint) as ending_qty
from {{ source('raw', 'fact_ledger') }}
where entry_type is not null
  and doc_no is not null
  and doc_date is not null
  and store_code is not null
  and product_code is not null
