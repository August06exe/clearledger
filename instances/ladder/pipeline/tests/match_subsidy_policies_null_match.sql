{{ config(severity='warn') }}
-- 匹配契约：主表 policy_code 在 subsidy_policies 中匹空的清单（未匹配标签）
select distinct w.policy_code
from {{ ref('int_ledger_wide') }} w
where w.policy_code is not null
  and not exists (
    select 1 from {{ ref('stg_subsidy_policies') }} d
    where d.policy_code = w.policy_code)
