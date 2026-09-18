
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        industry as value_field,
        count(*) as n_records

    from "sales"."staging"."stg_customers"
    group by industry

)

select *
from all_values
where value_field not in (
    '制造业','零售连锁','互联网','教育培训','医疗健康','金融服务'
)



  
  
      
    ) dbt_internal_test