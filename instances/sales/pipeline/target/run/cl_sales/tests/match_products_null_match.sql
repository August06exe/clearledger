
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
-- 匹配契约：主表 product_id 在 products 中匹空的清单（未匹配标签）
select distinct m.product_id
from "sales"."staging"."stg_sales_transactions" m
left join "sales"."staging"."stg_products" d on m.product_id = d.product_id
where m.product_id is not null and d.product_id is null
  
  
      
    ) dbt_internal_test