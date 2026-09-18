-- 生成物：报表汇总模型（月度经营总览 = 维度×指标）
select
date_trunc('month', doc_date) as "月份",
    sum(sales_net) as "销售额",
    sum(sales_cost) as "销售成本",
    sum(gross_profit) as "毛利",
    round(sum(gross_profit) / nullif(sum(sales_net), 0), 4) as "毛利率",
    sum(stock_qty) as "期末库存量",
    round(sum(sales_cost) / nullif(sum(stock_qty), 0), 4) as "库存周转率",
    round(sum(ecomm_net) / nullif(sum(sales_net), 0), 4) as "电商销售占比",
    count(distinct case when entry_type = '销售' then product_code end) as "动销商品数"
from {{ ref('int_wide_ledger') }}
where date_trunc('month', doc_date) < date_trunc('month', current_date)
group by 1
