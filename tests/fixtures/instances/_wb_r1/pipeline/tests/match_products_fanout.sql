{{ config(severity='warn') }}
-- 匹配契约：products 的键 product_code 必须唯一，否则 join 扇出/笛卡尔积
select product_code
from {{ ref('stg_products') }}
group by 1 having count(*) > 1
