-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(group_key as varchar)) as group_key,
    trim(cast(group_name as varchar)) as group_name,
    cast(budget_rate as decimal(18, 4)) as budget_rate
from {{ source('raw', 'group_params') }}
where group_key is not null
  and group_name is not null
