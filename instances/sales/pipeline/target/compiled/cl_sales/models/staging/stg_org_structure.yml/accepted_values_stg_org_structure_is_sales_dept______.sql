
    
    

with all_values as (

    select
        is_sales_dept as value_field,
        count(*) as n_records

    from "sales"."staging"."stg_org_structure"
    group by is_sales_dept

)

select *
from all_values
where value_field not in (
    '是','否'
)


