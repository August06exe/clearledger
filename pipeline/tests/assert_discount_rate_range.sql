{{ config(severity='warn') }}
-- 黄灯规则：折扣率必须在 [0, 1] 区间，脏折扣率会直接产生负收入
select
    order_id,
    discount_rate
from {{ ref('stg_sales') }}
where discount_rate < 0
   or discount_rate > 1
