{{ config(severity='error') }}
-- 匹配契约：customers 的键 customer_id 必须唯一，否则 join 扇出/笛卡尔积
select customer_id
from {{ ref('stg_customers') }}
group by 1 having count(*) > 1
