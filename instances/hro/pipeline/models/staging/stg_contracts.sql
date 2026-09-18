-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(contract_no as varchar)) as contract_no,
    trim(cast(customer_code as varchar)) as customer_code,
    trim(cast(bu_code as varchar)) as bu_code,
    trim(cast(bu_name as varchar)) as bu_name,
    cast(monthly_fee as decimal(18, 4)) as monthly_fee,
    trim(cast(start_month as varchar)) as start_month,
    trim(cast(end_month as varchar)) as end_month
from {{ source('raw', 'contracts') }}
where contract_no is not null
  and customer_code is not null
  and bu_code is not null
  and monthly_fee is not null
  and start_month is not null
  and end_month is not null
