-- 生成物：报表汇总模型（城市月报 = 维度×指标）
select
date_trunc('month', order_time) as "月份",
city as "城市",
    sum(amount) as "营业额",
    count(distinct order_no) as "客单数"
from "restaurant"."intermediate"."int_wide_orders"
where date_trunc('month', order_time) < date_trunc('month', current_date)
group by 1, 2