{{ config(severity='error') }}
-- 匹配契约：group_params 的键 group_key 必须唯一，否则 join 扇出/笛卡尔积
select group_key
from {{ ref('stg_group_params') }}
group by 1 having count(*) > 1
