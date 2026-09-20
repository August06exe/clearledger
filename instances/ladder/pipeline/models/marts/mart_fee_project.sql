-- 生成物：分层报表模型（L2.5 项目费用月报 ← revenue_project）
select
    "月份",
    "项目",
    sum(travel_fee) as "商旅费",
    sum(expense_fee) as "费用报销",
    sum(platform_fee) as "平台管理费",
    sum(levy) as "残保金",
    round(sum(travel_fee) + sum(expense_fee) + sum(platform_fee) + sum(levy), 2) as "期间费用合计"
from {{ ref('mart_revenue_project') }}
group by 1, 2
