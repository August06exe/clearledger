-- 生成物：分层报表模型（L5 集团净利月报 ← contribution_dept）
select
    "月份",
    + (+ (sum(revenue_amt))+ (sum(amort_rev))+ (sum(subsidy))- (+ (sum(salary))+ (sum(social_ins))+ (sum(recruit_fee)))- (+ (sum(travel_fee))+ (sum(expense_fee))+ (sum(platform_fee))+ (sum(levy))))- (sum(group_fee)) as "集团净利",
    round((sum(revenue_amt) + sum(amort_rev) + sum(subsidy) - sum(salary) - sum(social_ins) - sum(recruit_fee) - sum(travel_fee) - sum(expense_fee) - sum(platform_fee) - sum(levy) - sum(group_fee)) / nullif(sum(revenue_amt) + sum(amort_rev), 0), 4) as "净利率"
from {{ ref('mart_contribution_dept') }}
group by 1
