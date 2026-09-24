
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        entry_type as value_field,
        count(*) as n_records

    from "_wb_r1"."staging"."stg_fact_ledger"
    group by entry_type

)

select *
from all_values
where value_field not in (
    '销售','采购','采购退货','期末库存'
)



  
  
      
    ) dbt_internal_test