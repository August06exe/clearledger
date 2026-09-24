
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
-- 匹配契约：products 的键 product_code 必须唯一，否则 join 扇出/笛卡尔积
select product_code
from "_wb_r1"."staging"."stg_products"
group by 1 having count(*) > 1
  
  
      
    ) dbt_internal_test