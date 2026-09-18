
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select dept_code
from "sales"."staging"."stg_org_structure"
where dept_code is null



  
  
      
    ) dbt_internal_test