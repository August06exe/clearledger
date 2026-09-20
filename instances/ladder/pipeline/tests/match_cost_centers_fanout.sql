{{ config(severity='error') }}
-- 匹配契约：cost_centers 的键 cost_center_code 必须唯一，否则 join 扇出/笛卡尔积
select cost_center_code
from {{ ref('stg_cost_centers') }}
group by 1 having count(*) > 1
