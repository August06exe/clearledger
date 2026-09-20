-- 生成物：报表汇总模型（L1 项目收入月报 = 维度×指标）
select
date_trunc('month', period) as "月份",
project_name as "项目",
dept_name as "一级部门",
    sum(revenue_amt) as "收入",
    sum(amort_rev) as "摊销收入",
    sum(subsidy) as "政府补助",
    sum("amort_rev") as "amort_rev",
    sum("expense_fee") as "expense_fee",
    sum("group_fee") as "group_fee",
    sum("levy") as "levy",
    sum("platform_fee") as "platform_fee",
    sum("recruit_fee") as "recruit_fee",
    sum("revenue_amt") as "revenue_amt",
    sum("salary") as "salary",
    sum("social_ins") as "social_ins",
    sum("subsidy") as "subsidy",
    sum("travel_fee") as "travel_fee"
from {{ ref('int_ledger_wide') }}
where date_trunc('month', period) < date_trunc('month', current_date)
group by 1, 2, 3
