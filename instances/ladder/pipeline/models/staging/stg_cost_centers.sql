-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(cost_center_code as varchar)) as cost_center_code,
    trim(cast(cost_center_name as varchar)) as cost_center_name
from {{ source('raw', 'cost_centers') }}
where cost_center_code is not null
  and cost_center_name is not null
