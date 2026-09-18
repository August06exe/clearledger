
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select expense_date
from "sales"."staging"."stg_expenses"
where expense_date is null



  
  
      
    ) dbt_internal_test