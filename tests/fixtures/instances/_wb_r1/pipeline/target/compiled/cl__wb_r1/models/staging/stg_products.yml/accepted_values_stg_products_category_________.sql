
    
    

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


