{{ config(severity='warn') }}
-- 匹配契约：主表 dept_code 在 org 中匹空的清单（未匹配标签）
select distinct w.dept_code
from {{ ref('int_ledger_wide') }} w
where w.dept_code is not null
  and not exists (
    select 1 from {{ ref('stg_org') }} d
    where d.dept_code = w.dept_code)
