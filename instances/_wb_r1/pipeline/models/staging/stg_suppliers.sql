-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(supplier_code as varchar)) as supplier_code,
    trim(cast(supplier_name as varchar)) as supplier_name,
    trim(cast(settle_type as varchar)) as settle_type
from {{ source('raw', 'suppliers') }}
where supplier_code is not null
