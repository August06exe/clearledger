{{ config(severity='error') }}
-- 匹配契约：contracts 的键 contract_no 必须唯一，否则 join 扇出/笛卡尔积
select contract_no
from {{ ref('stg_contracts') }}
group by 1 having count(*) > 1
