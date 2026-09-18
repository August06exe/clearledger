{{ config(severity='warn') }}
-- 字段契约：数量 范围 [1, 100000]
select quantity
from {{ ref('stg_purchase_returns') }}
where quantity < 1 or quantity > 100000
