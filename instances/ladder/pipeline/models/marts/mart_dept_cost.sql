-- 生成物：报表汇总模型（部门人力成本月报 = 维度×指标）
select
date_trunc('month', period) as "月份",
dept_name as "一级部门",
    round(sum(salary) + sum(social_ins) + sum(recruit_fee), 2) as "人力成本"
from {{ ref('int_ledger_wide') }}
where date_trunc('month', period) < date_trunc('month', current_date)
group by 1, 2
