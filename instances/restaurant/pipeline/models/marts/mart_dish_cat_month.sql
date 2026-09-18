-- 生成物：报表汇总模型（菜类月报 = 维度×指标）
select
date_trunc('month', order_time) as "月份",
dish_cat as "菜品类别",
    sum(amount) as "营业额",
    sum(quantity) as "菜品销量"
from {{ ref('int_wide_orders') }}
where date_trunc('month', order_time) < date_trunc('month', current_date)
group by 1, 2
