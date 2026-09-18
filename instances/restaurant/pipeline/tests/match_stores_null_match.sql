{{ config(severity='warn') }}
-- 匹配契约：主表 store_code 在 stores 中匹空的清单（未匹配标签）
select distinct m.store_code
from {{ ref('stg_orders') }} m
left join {{ ref('stg_stores') }} d on m.store_code = d.store_code
where m.store_code is not null and d.store_code is null
