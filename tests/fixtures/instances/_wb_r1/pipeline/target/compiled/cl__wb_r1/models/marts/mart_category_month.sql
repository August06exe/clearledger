-- 生成物：报表汇总模型（品类月报 = 维度×指标）
select
date_trunc('month', doc_date) as "月份",
category as "品类",
    sum(sales_net) as "销售额",
    sum(sales_cost) as "销售成本",
    round(sum(gross_profit) / nullif(sum(sales_net), 0), 4) as "毛利率"
from "_wb_r1"."intermediate"."int_wide_ledger"
where date_trunc('month', doc_date) < date_trunc('month', current_date)
group by 1, 2