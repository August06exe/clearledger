-- 生成物：报表汇总模型（行业月报 = 维度×指标）
select
date_trunc('month', doc_month) as "月份",
industry as "行业",
customer_level as "客户级别",
    sum(bill_amt) as "服务费收入",
    sum(gross_amt) as "毛利",
    count(distinct case when entry_type = '在册' then employee_no end) as "外派人数"
from {{ ref('int_wide_hro') }}
where date_trunc('month', doc_month) < date_trunc('month', current_date)
group by 1, 2, 3
