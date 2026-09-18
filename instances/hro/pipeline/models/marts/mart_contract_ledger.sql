-- 生成物：报表汇总模型（合同台账 = 维度×指标）
select
contract_no as "合同",
    sum(bill_amt) as "服务费收入",
    sum(pay_amt) as "回款额",
    sum(bill_amt) - sum(pay_amt) as "应收余额",
    count(distinct case when entry_type = '在册' then employee_no end) as "外派人数"
from {{ ref('int_wide_hro') }}
group by 1
