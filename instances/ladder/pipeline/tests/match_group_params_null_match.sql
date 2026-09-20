{{ config(severity='warn') }}
-- 匹配契约：主表 group_key 在 group_params 中匹空的清单（未匹配标签）
select distinct w.group_key
from {{ ref('int_ledger_wide') }} w
where w.group_key is not null
  and not exists (
    select 1 from {{ ref('stg_group_params') }} d
    where d.group_key = w.group_key)
