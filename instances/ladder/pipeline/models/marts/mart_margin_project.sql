-- 生成物：分层报表模型（L2 项目毛利月报 ← revenue_project）
select
    "月份",
    "项目",
    "一级部门",
    sum(salary) as "工资奖金",
    sum(social_ins) as "社保公积金",
    sum(recruit_fee) as "招聘费",
    + (sum(salary))+ (sum(social_ins))+ (sum(recruit_fee)) as "人力成本",
    + (sum(revenue_amt))+ (sum(amort_rev))- (+ (sum(salary))+ (sum(social_ins))+ (sum(recruit_fee))) as "毛利",
    round((sum(revenue_amt) + sum(amort_rev) - sum(salary) - sum(social_ins) - sum(recruit_fee)) / nullif(sum(revenue_amt) + sum(amort_rev), 0), 4) as "毛利率",
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
from {{ ref('mart_revenue_project') }}
group by 1, 2, 3
