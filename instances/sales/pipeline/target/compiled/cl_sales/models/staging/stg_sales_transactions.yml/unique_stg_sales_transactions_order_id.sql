
    
    

select
    order_id as unique_field,
    count(*) as n_records

from "sales"."staging"."stg_sales_transactions"
where order_id is not null
group by order_id
having count(*) > 1


