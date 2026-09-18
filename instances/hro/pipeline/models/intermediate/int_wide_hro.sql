-- 生成物：宽表装配（hro_ledger + 3 张标签表有序左联 + 派生列）
select
    m.entry_type,
    m.doc_no,
    m.doc_month,
    m.contract_no,
    m.group_code,
    m.employee_no,
    m.emp_name,
    m.position,
    m.salary_cost,
    m.amount,
    d0.customer_code,
    d0.bu_name,
    d0.monthly_fee,
    d0.start_month,
    d0.end_month,
    d1.customer_name,
    d1.industry,
    d1.customer_level,
    d2.group_name,
    case when entry_type = '账单' then coalesce(amount, 0) else 0 end as "bill_amt",
    case when entry_type = '回款' then coalesce(amount, 0) else 0 end as "pay_amt",
    case when entry_type = '在册' then coalesce(salary_cost, 0) else 0 end as "cost_amt",
    case when entry_type = '账单' then coalesce(amount, 0) when entry_type = '在册' then -coalesce(salary_cost, 0) else 0 end as "gross_amt"
from {{ ref('stg_hro_ledger') }} m
left join {{ ref('stg_contracts') }} d0
  on m.contract_no = d0.contract_no
left join {{ ref('stg_customers') }} d1
  on d0.customer_code = d1.customer_code
left join {{ ref('stg_delivery_groups') }} d2
  on m.group_code = d2.group_code
