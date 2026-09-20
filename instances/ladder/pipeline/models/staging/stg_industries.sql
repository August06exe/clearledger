-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(industry_code as varchar)) as industry_code,
    trim(cast(industry_name as varchar)) as industry_name
from {{ source('raw', 'industries') }}
where industry_code is not null
  and industry_name is not null
