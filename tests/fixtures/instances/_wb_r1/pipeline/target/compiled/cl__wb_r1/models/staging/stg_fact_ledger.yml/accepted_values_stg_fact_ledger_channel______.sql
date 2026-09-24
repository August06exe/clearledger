
    
    

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


