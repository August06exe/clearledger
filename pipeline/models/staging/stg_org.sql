-- 组织架构 · 清洗层
-- 清洗规则：是否销售部门 由 是/否 规整为 1/0；空区域编码置 NULL
with src as (
    select * from {{ source('raw', 'org_structure') }}
)
select
    trim(dept_code)                                   as dept_code,
    trim(dept_name)                                   as dept_name,
    nullif(trim(parent_code), '')                     as parent_code,
    cast(dept_level as integer)                       as dept_level,
    case when trim(is_sales_dept) = '是' then 1 else 0 end as is_sales_dept,
    nullif(trim(region_code), '')                     as region_code
from src
where dept_code is not null
