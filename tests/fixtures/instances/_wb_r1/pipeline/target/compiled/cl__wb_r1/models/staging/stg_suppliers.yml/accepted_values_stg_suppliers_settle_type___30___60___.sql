
    
    

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


