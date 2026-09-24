
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        channel as value_field,
        count(*) as n_records

    from "_wb_r1"."staging"."stg_fact_ledger"
    group by channel

)

select *
from all_values
where value_field not in (
    '门店','电商'
)



  
  
      
    ) dbt_internal_test