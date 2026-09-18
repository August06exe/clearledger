
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
-- 匹配契约：customers 的键 customer_id 必须唯一，否则 join 扇出/笛卡尔积
select customer_id
from "sales"."staging"."stg_customers"
group by 1 having count(*) > 1
  
  
      
    ) dbt_internal_test