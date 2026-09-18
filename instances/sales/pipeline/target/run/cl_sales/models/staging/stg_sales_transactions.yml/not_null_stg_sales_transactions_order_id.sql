
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select order_id
from "sales"."staging"."stg_sales_transactions"
where order_id is null



  
  
      
    ) dbt_internal_test