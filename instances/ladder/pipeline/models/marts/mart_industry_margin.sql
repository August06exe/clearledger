-- 生成物：报表汇总模型（行业毛利月报 = 维度×指标）
select
date_trunc('month', period) as "月份",
industry_name as "行业",
    sum(revenue_amt) as "收入",
    + (sum(revenue_amt))+ (sum(amort_rev))- (+ (sum(salary))+ (sum(social_ins))+ (sum(recruit_fee))) as "毛利",
    round((sum(revenue_amt) + sum(amort_rev) - sum(salary) - sum(social_ins) - sum(recruit_fee)) / nullif(sum(revenue_amt) + sum(amort_rev), 0), 4) as "毛利率"
from {{ ref('int_ledger_wide') }}
where date_trunc('month', period) < date_trunc('month', current_date)
group by 1, 2
