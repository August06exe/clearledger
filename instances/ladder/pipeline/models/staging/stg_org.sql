-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(dept_code as varchar)) as dept_code,
    trim(cast(dept_name as varchar)) as dept_name
from {{ source('raw', 'org') }}
where dept_code is not null
  and dept_name is not null
