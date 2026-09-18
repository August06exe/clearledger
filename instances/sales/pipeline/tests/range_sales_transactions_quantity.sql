{{ config(severity='warn') }}
-- 字段契约：数量 范围 [1, 1000000]
select quantity
from {{ ref('stg_sales_transactions') }}
where quantity < 1 or quantity > 1000000
