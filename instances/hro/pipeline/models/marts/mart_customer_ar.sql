-- 生成物：报表汇总模型（客户应收榜 = 维度×指标）
select
customer_name as "客户",
industry as "行业",
customer_level as "客户级别",
    sum(bill_amt) as "服务费收入",
    sum(pay_amt) as "回款额",
    sum(bill_amt) - sum(pay_amt) as "应收余额",
    count(distinct case when entry_type = '账单' then contract_no end) as "在单合同数"
from {{ ref('int_wide_hro') }}
group by 1, 2, 3
