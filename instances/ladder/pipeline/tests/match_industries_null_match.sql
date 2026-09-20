{{ config(severity='warn') }}
-- 匹配契约：主表 industry_code 在 industries 中匹空的清单（未匹配标签）
select distinct w.industry_code
from {{ ref('int_ledger_wide') }} w
where w.industry_code is not null
  and not exists (
    select 1 from {{ ref('stg_industries') }} d
    where d.industry_code = w.industry_code)
