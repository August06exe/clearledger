{{ config(severity='warn') }}
-- 字段契约：账单金额 范围 [0, 100000000]
select amount
from {{ ref('stg_bills') }}
where amount < 0 or amount > 100000000
