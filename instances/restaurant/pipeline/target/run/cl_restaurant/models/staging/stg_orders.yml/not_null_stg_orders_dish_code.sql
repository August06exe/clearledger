
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select dish_code
from "restaurant"."staging"."stg_orders"
where dish_code is null



  
  
      
    ) dbt_internal_test