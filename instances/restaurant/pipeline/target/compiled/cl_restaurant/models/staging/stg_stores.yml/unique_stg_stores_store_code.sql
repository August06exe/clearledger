
    
    

select
    store_code as unique_field,
    count(*) as n_records

from "restaurant"."staging"."stg_stores"
where store_code is not null
group by store_code
having count(*) > 1


