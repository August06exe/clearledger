{{ config(severity='warn') }}
-- 匹配契约：主表 dish_code 在 dishes 中匹空的清单（未匹配标签）
select distinct w.dish_code
from {{ ref('int_wide_orders') }} w
where w.dish_code is not null
  and not exists (
    select 1 from {{ ref('stg_dishes') }} d
    where d.dish_code = w.dish_code)
