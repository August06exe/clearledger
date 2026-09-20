-- 生成物：宽表装配（ledger + 7 张标签表有序左联 + 派生列）
select
    m.period,
    m.project_code,
    m.revenue_amt,
    m.amort_rev,
    m.subsidy,
    m.salary,
    m.social_ins,
    m.recruit_fee,
    m.travel_fee,
    m.expense_fee,
    m.platform_fee,
    m.levy,
    m.group_fee,
    m.customer_code,
    m.industry_code,
    m.cost_center_code,
    m.policy_code,
    m.group_key,
    d0.project_name,
    d0.dept_code,
    d1.dept_name,
    d2.customer_name,
    d3.industry_name,
    d4.cost_center_name,
    d5.policy_name,
    d5.subsidy_type,
    d6.group_name,
    d6.budget_rate
from {{ ref('stg_ledger') }} m
left join {{ ref('stg_projects') }} d0
  on m.project_code = d0.project_code
left join {{ ref('stg_org') }} d1
  on d0.dept_code = d1.dept_code
left join {{ ref('stg_customers') }} d2
  on m.customer_code = d2.customer_code
left join {{ ref('stg_industries') }} d3
  on m.industry_code = d3.industry_code
left join {{ ref('stg_cost_centers') }} d4
  on m.cost_center_code = d4.cost_center_code
left join {{ ref('stg_subsidy_policies') }} d5
  on m.policy_code = d5.policy_code
left join {{ ref('stg_group_params') }} d6
  on m.group_key = d6.group_key
