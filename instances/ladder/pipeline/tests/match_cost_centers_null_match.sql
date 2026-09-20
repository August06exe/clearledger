{{ config(severity='warn') }}
-- 匹配契约：主表 cost_center_code 在 cost_centers 中匹空的清单（未匹配标签）
select distinct w.cost_center_code
from {{ ref('int_ledger_wide') }} w
where w.cost_center_code is not null
  and not exists (
    select 1 from {{ ref('stg_cost_centers') }} d
    where d.cost_center_code = w.cost_center_code)
