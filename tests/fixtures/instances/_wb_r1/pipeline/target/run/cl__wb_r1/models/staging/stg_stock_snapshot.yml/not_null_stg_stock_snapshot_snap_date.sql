
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select snap_date
from "_wb_r1"."staging"."stg_stock_snapshot"
where snap_date is null



  
  
      
    ) dbt_internal_test