-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(store_code as varchar)) as store_code,
    trim(cast(promo_name as varchar)) as promo_name,
    cast(start_date as date) as start_date,
    cast(end_date as date) as end_date,
    cast(discount as decimal(18, 4)) as discount
from {{ source('raw', 'promotions') }}
where store_code is not null
  and start_date is not null
