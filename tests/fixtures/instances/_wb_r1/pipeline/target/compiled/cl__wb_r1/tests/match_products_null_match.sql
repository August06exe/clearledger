
-- 匹配契约：主表 product_code 在 products 中匹空的清单（未匹配标签）
select distinct w.product_code
from "_wb_r1"."intermediate"."int_wide_ledger" w
where w.product_code is not null
  and not exists (
    select 1 from "_wb_r1"."staging"."stg_products" d
    where d.product_code = w.product_code)