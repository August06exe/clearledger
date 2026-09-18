
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    dept_code as unique_field,
    count(*) as n_records

from "sales"."staging"."stg_org_structure"
where dept_code is not null
group by dept_code
having count(*) > 1



  
  
      
    ) dbt_internal_test