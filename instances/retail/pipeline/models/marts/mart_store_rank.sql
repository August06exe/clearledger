-- 生成物：报表汇总模型（门店排行 = 维度×指标）
select
store_name as "门店",
    sum(sales_net) as "销售额",
    sum(gross_profit) as "毛利",
    round(sum(gross_profit) / nullif(sum(sales_net), 0), 4) as "毛利率",
    round(sum(sales_cost) / nullif(sum(stock_qty), 0), 4) as "库存周转率"
from {{ ref('int_wide_ledger') }}
group by 1
