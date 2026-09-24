
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        settle_type as value_field,
        count(*) as n_records

    from "_wb_r1"."staging"."stg_suppliers"
    group by settle_type

)

select *
from all_values
where value_field not in (
    '月结30','月结60','现结'
)



  
  
      
    ) dbt_internal_test