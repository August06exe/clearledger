-- 生成物：报表汇总模型（月度经营总览 = 维度×指标）
select
date_trunc('month', doc_month) as "月份",
    sum(bill_amt) as "服务费收入",
    sum(cost_amt) as "人力成本",
    sum(gross_amt) as "毛利",
    round(sum(gross_amt) / nullif(sum(bill_amt), 0), 4) as "毛利率",
    sum(pay_amt) as "回款额",
    round(sum(pay_amt) / nullif(sum(bill_amt), 0), 4) as "回款率",
    count(distinct case when entry_type = '在册' then employee_no end) as "外派人数",
    round(sum(bill_amt) / nullif(count(distinct case when entry_type = '在册' then employee_no end), 0), 2) as "人均产值",
    count(distinct case when entry_type = '账单' then customer_code end) as "在单客户数"
from {{ ref('int_wide_hro') }}
where date_trunc('month', doc_month) < date_trunc('month', current_date)
group by 1
