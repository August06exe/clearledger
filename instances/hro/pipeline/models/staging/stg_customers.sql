-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(customer_code as varchar)) as customer_code,
    trim(cast(customer_name as varchar)) as customer_name,
    trim(cast(industry as varchar)) as industry,
    trim(cast(customer_level as varchar)) as customer_level
from {{ source('raw', 'customers') }}
where customer_code is not null
