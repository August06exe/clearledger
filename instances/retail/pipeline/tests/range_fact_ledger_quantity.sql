{{ config(severity='warn') }}
-- 字段契约：数量 范围 [1, 1000]
select quantity
from {{ ref('stg_fact_ledger') }}
where quantity < 1 or quantity > 1000
