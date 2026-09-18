-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    cast(expense_date as date) as expense_date,
    trim(cast(dept_code as varchar)) as dept_code,
    trim(cast(dept_name as varchar)) as dept_name,
    trim(cast(category as varchar)) as category,
    cast(amount as decimal(18, 4)) as amount
from "sales"."raw"."expenses"
where expense_date is not null
  and dept_code is not null
  and amount is not null