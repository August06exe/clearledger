-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(snap_month as varchar)) as snap_month,
    cast(snap_date as date) as snap_date,
    trim(cast(store_code as varchar)) as store_code,
    trim(cast(product_code as varchar)) as product_code,
    cast(ending_qty as bigint) as ending_qty
from {{ source('raw', 'stock_snapshot') }}
where snap_date is not null
  and store_code is not null
  and product_code is not null
  and ending_qty is not null
