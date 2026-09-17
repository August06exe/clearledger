-- 部门费用 · 清洗层
with src as (
    select * from {{ source('raw', 'expenses') }}
)
select
    cast(expense_date as date)         as expense_date,
    trim(dept_code)                    as dept_code,
    trim(dept_name)                    as dept_name,
    trim(category)                     as category,
    cast(amount as decimal(18, 2))     as amount
from src
where dept_code is not null
  and expense_date is not null
