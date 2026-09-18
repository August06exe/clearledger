-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(customer_id as varchar)) as customer_id,
    trim(cast(customer_name as varchar)) as customer_name,
    trim(cast(industry as varchar)) as industry,
    trim(cast(customer_level as varchar)) as customer_level,
    trim(cast(region_code as varchar)) as region_code,
    trim(cast(region_name as varchar)) as region_name,
    trim(cast(status as varchar)) as status
from "sales"."raw"."customers"
where customer_id is not null