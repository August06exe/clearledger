
  
  create view "sales"."staging"."stg_products__dbt_tmp" as (
    -- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(product_id as varchar)) as product_id,
    trim(cast(product_name as varchar)) as product_name,
    trim(cast(category as varchar)) as category,
    trim(cast(unit as varchar)) as unit,
    cast(std_price as decimal(18, 4)) as std_price,
    cast(std_cost as decimal(18, 4)) as std_cost
from "sales"."raw"."products"
where product_id is not null
  );
