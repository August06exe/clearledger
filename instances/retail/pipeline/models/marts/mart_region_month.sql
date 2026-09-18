-- 生成物：报表汇总模型（大区月报 = 维度×指标）
select
date_trunc('month', doc_date) as "月份",
region_name as "大区",
    sum(sales_net) as "销售额",
    sum(purchase_amt) - sum(return_amt) as "净采购",
    sum(gross_profit) as "毛利",
    round(sum(gross_profit) / nullif(sum(sales_net), 0), 4) as "毛利率"
from {{ ref('int_wide_ledger') }}
where date_trunc('month', doc_date) < date_trunc('month', current_date)
group by 1, 2
