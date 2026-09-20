{{ config(severity='warn') }}
-- 匹配契约：主表 customer_code 在 customers 中匹空的清单（未匹配标签）
select distinct w.customer_code
from {{ ref('int_ledger_wide') }} w
where w.customer_code is not null
  and not exists (
    select 1 from {{ ref('stg_customers') }} d
    where d.customer_code = w.customer_code)
