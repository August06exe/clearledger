-- 生成物：报表汇总模型（行业经营汇总 = 维度×指标）
select
industry as "行业",
    sum(net_amount) as "收入",
    sum(gross_profit) as "毛利",
    round(sum(gross_profit) / nullif(sum(net_amount), 0), 4) as "毛利率",
    count(distinct customer_id) as "客户数"
from "sales"."intermediate"."int_wide_sales"
group by 1