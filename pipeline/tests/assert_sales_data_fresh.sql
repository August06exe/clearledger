{{ config(severity='warn') }}
-- 黄灯规则：销售流水最近订单日距今超过 3 天 → 提醒源文件可能断更
select
    current_date as today,
    max(order_date) as max_order_date
from {{ ref('stg_sales') }}
having max(order_date) < current_date - interval '3' day
