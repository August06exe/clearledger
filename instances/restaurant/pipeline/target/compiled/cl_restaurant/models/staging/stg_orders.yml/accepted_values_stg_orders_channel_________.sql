
    
    

with all_values as (

    select
        channel as value_field,
        count(*) as n_records

    from "restaurant"."staging"."stg_orders"
    group by channel

)

select *
from all_values
where value_field not in (
    '堂食','外卖','小程序'
)


