
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select ending_qty
from "_wb_r1"."staging"."stg_stock_snapshot"
where ending_qty is null



  
  
      
    ) dbt_internal_test