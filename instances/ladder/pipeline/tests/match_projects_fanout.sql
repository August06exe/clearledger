{{ config(severity='error') }}
-- 匹配契约：projects 的键 project_code 必须唯一，否则 join 扇出/笛卡尔积
select project_code
from {{ ref('stg_projects') }}
group by 1 having count(*) > 1
