-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(product_code as varchar)) as product_code,
    trim(cast(product_name as varchar)) as product_name,
    trim(cast(category as varchar)) as category,
    trim(cast(unit as varchar)) as unit,
    cast(std_cost as decimal(18, 4)) as std_cost
from "_wb_r1"."raw"."products"
where product_code is not null