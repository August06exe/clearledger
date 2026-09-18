-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(dept_code as varchar)) as dept_code,
    trim(cast(dept_name as varchar)) as dept_name,
    trim(cast(parent_code as varchar)) as parent_code,
    cast(dept_level as bigint) as dept_level,
    trim(cast(is_sales_dept as varchar)) as is_sales_dept,
    trim(cast(region_code as varchar)) as region_code
from {{ source('raw', 'org_structure') }}
where dept_code is not null
