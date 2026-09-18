-- 生成物：报表汇总模型（门店经营排行 = 维度×指标）
select
store_name as "门店",
    sum(amount) as "营业额",
    sum(gross_profit) as "毛利",
    count(distinct order_no) as "客单数",
    round(sum(gross_profit) / nullif(sum(amount), 0), 4) as "毛利率"
from {{ ref('int_wide_orders') }}
group by 1
