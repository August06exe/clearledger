-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(group_code as varchar)) as group_code,
    trim(cast(group_name as varchar)) as group_name,
    trim(cast(bu_code as varchar)) as bu_code
from {{ source('raw', 'delivery_groups') }}
where group_code is not null
  and bu_code is not null
