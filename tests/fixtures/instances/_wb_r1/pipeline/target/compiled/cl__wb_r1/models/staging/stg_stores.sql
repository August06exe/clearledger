-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(store_code as varchar)) as store_code,
    trim(cast(store_name as varchar)) as store_name,
    trim(cast(city as varchar)) as city,
    trim(cast(region_name as varchar)) as region_name,
    cast(open_date as date) as open_date
from "_wb_r1"."raw"."stores"
where store_code is not null