-- 生成物：报表汇总模型（区域经营月报 = 维度×指标）
select
date_trunc('month', order_date) as "月份",
region_name as "区域",
    sum(net_amount) as "收入",
    sum(gross_profit) as "毛利",
    round(sum(gross_profit) / nullif(sum(net_amount), 0), 4) as "毛利率"
from {{ ref('int_wide_sales') }}
where date_trunc('month', order_date) < date_trunc('month', current_date)
group by 1, 2
