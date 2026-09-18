-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    cast(doc_month as date) as doc_month,
    trim(cast(contract_no as varchar)) as contract_no,
    cast(amount as decimal(18, 4)) as amount
from {{ source('raw', 'payments') }}
where doc_month is not null
  and contract_no is not null
