-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(store_code as varchar)) as store_code,
    trim(cast(store_name as varchar)) as store_name,
    trim(cast(city as varchar)) as city,
    trim(cast(biz_type as varchar)) as biz_type
from {{ source('raw', 'stores') }}
where store_code is not null
