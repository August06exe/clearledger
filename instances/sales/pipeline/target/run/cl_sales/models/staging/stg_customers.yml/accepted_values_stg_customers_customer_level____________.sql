
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        customer_level as value_field,
        count(*) as n_records

    from "sales"."staging"."stg_customers"
    group by customer_level

)

select *
from all_values
where value_field not in (
    '战略客户','大客户','中型客户','小微企业'
)



  
  
      
    ) dbt_internal_test