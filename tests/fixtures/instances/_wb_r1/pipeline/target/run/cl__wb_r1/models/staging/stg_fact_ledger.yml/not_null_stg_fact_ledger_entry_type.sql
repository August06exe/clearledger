
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select entry_type
from "_wb_r1"."staging"."stg_fact_ledger"
where entry_type is null



  
  
      
    ) dbt_internal_test