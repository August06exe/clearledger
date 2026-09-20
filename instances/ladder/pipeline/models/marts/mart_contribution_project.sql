-- 生成物：分层报表模型（L3 项目贡献月报 ← margin_project）
select
    "月份",
    "项目",
    "一级部门",
    round(sum(revenue_amt) + sum(amort_rev) + sum(subsidy) - sum(salary) - sum(social_ins) - sum(recruit_fee) - sum(travel_fee) - sum(expense_fee) - sum(platform_fee) - sum(levy), 2) as "责任贡献",
    round((sum(revenue_amt) + sum(amort_rev) + sum(subsidy) - sum(salary) - sum(social_ins) - sum(recruit_fee) - sum(travel_fee) - sum(expense_fee) - sum(platform_fee) - sum(levy)) / nullif(sum(revenue_amt) + sum(amort_rev), 0), 4) as "贡献率",
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
from {{ ref('mart_margin_project') }}
group by 1, 2, 3
