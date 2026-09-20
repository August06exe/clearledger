{{ config(severity='warn') }}
-- 匹配契约：主表 project_code 在 projects 中匹空的清单（未匹配标签）
select distinct w.project_code
from {{ ref('int_ledger_wide') }} w
where w.project_code is not null
  and not exists (
    select 1 from {{ ref('stg_projects') }} d
    where d.project_code = w.project_code)
