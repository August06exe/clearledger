{{ config(severity='warn') }}
-- 匹配契约：主表 customer_id 在 customers 中匹空的清单（未匹配标签）
select distinct w.customer_id
from {{ ref('int_wide_sales') }} w
where w.customer_id is not null
  and not exists (
    select 1 from {{ ref('stg_customers') }} d
    where d.customer_id = w.customer_id)
