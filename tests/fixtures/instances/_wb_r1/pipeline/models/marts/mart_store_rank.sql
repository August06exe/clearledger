-- 生成物：报表汇总模型（门店排行 = 维度×指标）
select
store_name as "门店",
    sum(sales_net) as "销售额",
    sum(gross_profit) as "毛利",
    sum(stock_qty) as "期末库存量"
from {{ ref('int_wide_ledger') }}
group by 1
