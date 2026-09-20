-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    cast(period as date) as period,
    trim(cast(project_code as varchar)) as project_code,
    cast(revenue_amt as decimal(18, 4)) as revenue_amt,
    cast(amort_rev as decimal(18, 4)) as amort_rev,
    cast(subsidy as decimal(18, 4)) as subsidy,
    cast(salary as decimal(18, 4)) as salary,
    cast(social_ins as decimal(18, 4)) as social_ins,
    cast(recruit_fee as decimal(18, 4)) as recruit_fee,
    cast(travel_fee as decimal(18, 4)) as travel_fee,
    cast(expense_fee as decimal(18, 4)) as expense_fee,
    cast(platform_fee as decimal(18, 4)) as platform_fee,
    cast(levy as decimal(18, 4)) as levy,
    cast(group_fee as decimal(18, 4)) as group_fee,
    trim(cast(customer_code as varchar)) as customer_code,
    trim(cast(industry_code as varchar)) as industry_code,
    trim(cast(cost_center_code as varchar)) as cost_center_code,
    trim(cast(policy_code as varchar)) as policy_code,
    trim(cast(group_key as varchar)) as group_key
from {{ source('raw', 'ledger') }}
where period is not null
  and project_code is not null
  and group_key is not null
