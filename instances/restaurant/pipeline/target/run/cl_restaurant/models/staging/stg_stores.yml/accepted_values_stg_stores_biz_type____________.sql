
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

with all_values as (

    select
        biz_type as value_field,
        count(*) as n_records

    from "restaurant"."staging"."stg_stores"
    group by biz_type

)

select *
from all_values
where value_field not in (
    '购物中心','社区','交通枢纽','景区'
)



  
  
      
    ) dbt_internal_test