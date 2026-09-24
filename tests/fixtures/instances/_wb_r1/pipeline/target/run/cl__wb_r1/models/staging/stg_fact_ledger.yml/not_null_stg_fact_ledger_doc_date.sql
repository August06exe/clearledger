
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select doc_date
from "_wb_r1"."staging"."stg_fact_ledger"
where doc_date is null



  
  
      
    ) dbt_internal_test