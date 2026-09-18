
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
-- 匹配契约：主表 store_code 在 stores 中匹空的清单（未匹配标签）
select distinct m.store_code
from "restaurant"."staging"."stg_orders" m
left join "restaurant"."staging"."stg_stores" d on m.store_code = d.store_code
where m.store_code is not null and d.store_code is null
  
  
      
    ) dbt_internal_test