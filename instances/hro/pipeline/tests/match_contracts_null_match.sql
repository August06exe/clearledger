{{ config(severity='warn') }}
-- 匹配契约：主表 contract_no 在 contracts 中匹空的清单（未匹配标签）
select distinct w.contract_no
from {{ ref('int_wide_hro') }} w
where w.contract_no is not null
  and not exists (
    select 1 from {{ ref('stg_contracts') }} d
    where d.contract_no = w.contract_no)
