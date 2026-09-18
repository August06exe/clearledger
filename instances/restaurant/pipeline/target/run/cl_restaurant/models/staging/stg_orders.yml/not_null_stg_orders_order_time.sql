
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select order_time
from "restaurant"."staging"."stg_orders"
where order_time is null



  
  
      
    ) dbt_internal_test