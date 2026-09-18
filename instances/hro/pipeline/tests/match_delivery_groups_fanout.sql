{{ config(severity='error') }}
-- 匹配契约：delivery_groups 的键 group_code 必须唯一，否则 join 扇出/笛卡尔积
select group_code
from {{ ref('stg_delivery_groups') }}
group by 1 having count(*) > 1
