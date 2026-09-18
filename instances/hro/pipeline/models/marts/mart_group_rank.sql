-- 生成物：报表汇总模型（交付组排行 = 维度×指标）
select
group_name as "交付组",
bu_name as "事业部",
    count(distinct case when entry_type = '在册' then employee_no end) as "外派人数",
    sum(cost_amt) as "人力成本",
    round(sum(cost_amt) / nullif(count(distinct case when entry_type = '在册' then employee_no end), 0), 2) as "人均人力成本"
from {{ ref('int_wide_hro') }}
group by 1, 2
