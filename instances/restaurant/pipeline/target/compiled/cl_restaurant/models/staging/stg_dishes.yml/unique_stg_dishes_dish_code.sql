
    
    

select
    dish_code as unique_field,
    count(*) as n_records

from "restaurant"."staging"."stg_dishes"
where dish_code is not null
group by dish_code
having count(*) > 1


