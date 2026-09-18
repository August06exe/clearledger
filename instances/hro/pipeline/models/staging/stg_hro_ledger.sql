-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(entry_type as varchar)) as entry_type,
    trim(cast(doc_no as varchar)) as doc_no,
    cast(doc_month as date) as doc_month,
    trim(cast(contract_no as varchar)) as contract_no,
    trim(cast(group_code as varchar)) as group_code,
    trim(cast(employee_no as varchar)) as employee_no,
    trim(cast(emp_name as varchar)) as emp_name,
    coalesce(trim(cast(position as varchar)), '未分类') as position,
    coalesce(cast(salary_cost as decimal(18, 4)), 0) as salary_cost,
    cast(amount as decimal(18, 4)) as amount
from {{ source('raw', 'hro_ledger') }}
where entry_type is not null
  and doc_no is not null
  and doc_month is not null
  and contract_no is not null
