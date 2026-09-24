
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        category as value_field,
        count(*) as n_records

    from "_wb_r1"."staging"."stg_products"
    group by category

)

select *
from all_values
where value_field not in (
    '食品','百货','日化'
)



  
  
      
    ) dbt_internal_test