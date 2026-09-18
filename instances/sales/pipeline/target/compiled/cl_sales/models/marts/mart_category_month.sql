-- 生成物：报表汇总模型（品类月报 = 维度×指标）
select
date_trunc('month', order_date) as "月份",
category as "品类",
    sum(net_amount) as "收入",
    sum(gross_profit) as "毛利"
from "sales"."intermediate"."int_wide_sales"
where date_trunc('month', order_date) < date_trunc('month', current_date)
group by 1, 2