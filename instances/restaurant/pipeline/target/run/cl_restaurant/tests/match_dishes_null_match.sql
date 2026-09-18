
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
-- 匹配契约：主表 dish_code 在 dishes 中匹空的清单（未匹配标签）
select distinct m.dish_code
from "restaurant"."staging"."stg_orders" m
left join "restaurant"."staging"."stg_dishes" d on m.dish_code = d.dish_code
where m.dish_code is not null and d.dish_code is null
  
  
      
    ) dbt_internal_test