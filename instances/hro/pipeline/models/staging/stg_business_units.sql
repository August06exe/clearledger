-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(bu_code as varchar)) as bu_code,
    trim(cast(bu_name as varchar)) as bu_name,
    trim(cast(bu_owner as varchar)) as bu_owner
from {{ source('raw', 'business_units') }}
where bu_code is not null
