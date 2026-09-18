-- 生成物：宽表装配（orders + 2 张标签表左联 + 派生列）
select
    m.order_no,
    m.order_time,
    m.store_code,
    m.dish_code,
    m.quantity,
    m.unit_price,
    m.amount,
    m.channel,
    d0.dish_name,
    d0.dish_cat,
    d0.std_cost,
    d1.store_name,
    d1.city,
    d1.biz_type,
    round(quantity * std_cost, 2) as cost_amount,
    round(amount - quantity * std_cost, 2) as gross_profit
from "restaurant"."staging"."stg_orders" m
left join "restaurant"."staging"."stg_dishes" d0
  on m.dish_code = d0.dish_code
left join "restaurant"."staging"."stg_stores" d1
  on m.store_code = d1.store_code