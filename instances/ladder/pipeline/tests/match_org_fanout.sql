{{ config(severity='error') }}
-- 匹配契约：org 的键 dept_code 必须唯一，否则 join 扇出/笛卡尔积
select dept_code
from {{ ref('stg_org') }}
group by 1 having count(*) > 1
