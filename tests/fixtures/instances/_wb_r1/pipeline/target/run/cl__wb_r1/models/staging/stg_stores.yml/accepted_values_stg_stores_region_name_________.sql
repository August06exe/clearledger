
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        region_name as value_field,
        count(*) as n_records

    from "_wb_r1"."staging"."stg_stores"
    group by region_name

)

select *
from all_values
where value_field not in (
    '华东','华北','华南'
)



  
  
      
    ) dbt_internal_test