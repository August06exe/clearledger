-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(project_code as varchar)) as project_code,
    trim(cast(project_name as varchar)) as project_name,
    trim(cast(dept_code as varchar)) as dept_code,
    trim(cast(project_manager as varchar)) as project_manager
from {{ source('raw', 'projects') }}
where project_code is not null
  and project_name is not null
  and dept_code is not null
