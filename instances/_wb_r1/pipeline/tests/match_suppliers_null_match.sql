{{ config(severity='warn') }}
-- 匹配契约：主表 supplier_code 在 suppliers 中匹空的清单（未匹配标签）
select distinct w.supplier_code
from {{ ref('int_wide_ledger') }} w
where w.supplier_code is not null
  and not exists (
    select 1 from {{ ref('stg_suppliers') }} d
    where d.supplier_code = w.supplier_code)
