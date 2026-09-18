{{ config(severity='error') }}
-- 匹配契约：stores 的键 store_code 必须唯一，否则 join 扇出/笛卡尔积
select store_code
from {{ ref('stg_stores') }}
group by 1 having count(*) > 1
