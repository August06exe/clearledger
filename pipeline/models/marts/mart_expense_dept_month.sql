-- 部门费用月历：月 × 部门 × 费用类别（分摊后口径）
select
    month,
    dept_code,
    dept_name,
    category,
    round(sum(allocated_amount), 2) as allocated_amount
from {{ ref('int_expense_alloc') }}
group by 1, 2, 3, 4
