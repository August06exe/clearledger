
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select amount
from "restaurant"."staging"."stg_orders"
where amount is null



  
  
      
    ) dbt_internal_test