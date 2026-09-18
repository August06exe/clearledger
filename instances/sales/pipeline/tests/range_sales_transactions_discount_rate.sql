{{ config(severity='warn') }}
-- 字段契约：折扣率 范围 [0, 1]
select discount_rate
from {{ ref('stg_sales_transactions') }}
where discount_rate < 0 or discount_rate > 1
