-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(order_no as varchar)) as order_no,
    cast(order_time as date) as order_time,
    trim(cast(store_code as varchar)) as store_code,
    trim(cast(dish_code as varchar)) as dish_code,
    cast(quantity as bigint) as quantity,
    cast(unit_price as decimal(18, 4)) as unit_price,
    cast(amount as decimal(18, 4)) as amount,
    trim(cast(channel as varchar)) as channel
from "restaurant"."raw"."orders"
where order_no is not null
  and order_time is not null
  and store_code is not null
  and dish_code is not null
  and quantity is not null
  and amount is not null