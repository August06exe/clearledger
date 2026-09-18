{{ config(severity='warn') }}
-- 匹配契约：主表 product_id 在 products 中匹空的清单（未匹配标签）
select distinct w.product_id
from {{ ref('int_wide_sales') }} w
where w.product_id is not null
  and not exists (
    select 1 from {{ ref('stg_products') }} d
    where d.product_id = w.product_id)
