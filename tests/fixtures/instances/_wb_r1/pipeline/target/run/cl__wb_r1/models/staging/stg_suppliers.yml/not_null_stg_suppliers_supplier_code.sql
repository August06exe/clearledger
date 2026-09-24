
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select supplier_code
from "_wb_r1"."staging"."stg_suppliers"
where supplier_code is null



  
  
      
    ) dbt_internal_test