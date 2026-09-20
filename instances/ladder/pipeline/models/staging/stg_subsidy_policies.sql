-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(policy_code as varchar)) as policy_code,
    trim(cast(policy_name as varchar)) as policy_name,
    trim(cast(subsidy_type as varchar)) as subsidy_type
from {{ source('raw', 'subsidy_policies') }}
where policy_code is not null
  and policy_name is not null
