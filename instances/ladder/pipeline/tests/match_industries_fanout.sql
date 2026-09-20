{{ config(severity='error') }}
-- 匹配契约：industries 的键 industry_code 必须唯一，否则 join 扇出/笛卡尔积
select industry_code
from {{ ref('stg_industries') }}
group by 1 having count(*) > 1
