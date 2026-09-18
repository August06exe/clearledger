{{ config(severity='warn') }}
-- 匹配契约：主表 group_code 在 delivery_groups 中匹空的清单（未匹配标签）
select distinct w.group_code
from {{ ref('int_wide_hro') }} w
where w.group_code is not null
  and not exists (
    select 1 from {{ ref('stg_delivery_groups') }} d
    where d.group_code = w.group_code)
