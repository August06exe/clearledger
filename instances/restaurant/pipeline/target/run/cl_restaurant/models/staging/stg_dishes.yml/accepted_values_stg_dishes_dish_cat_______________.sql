
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        dish_cat as value_field,
        count(*) as n_records

    from "restaurant"."staging"."stg_dishes"
    group by dish_cat

)

select *
from all_values
where value_field not in (
    '热菜','凉菜','主食','饮品','甜点'
)



  
  
      
    ) dbt_internal_test