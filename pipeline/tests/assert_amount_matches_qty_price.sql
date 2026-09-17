{{ config(severity='warn') }}
-- 黄灯规则：折前金额应等于 数量 × 单价（允许分位误差）。
-- 不符说明源文件口径漂移（源 amount 列被人为改动），收入/毛利全链路可信度受损。
select
    order_id,
    amount,
    quantity,
    unit_price
from {{ ref('stg_sales') }}
where abs(amount - quantity * unit_price) > 0.05
