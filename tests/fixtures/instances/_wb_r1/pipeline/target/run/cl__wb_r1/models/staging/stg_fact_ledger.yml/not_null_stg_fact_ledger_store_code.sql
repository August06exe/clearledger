
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select store_code
from "_wb_r1"."staging"."stg_fact_ledger"
where store_code is null



  
  
      
    ) dbt_internal_test