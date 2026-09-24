
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
-- 字段契约：数量 范围 [1, 999]
select quantity
from "_wb_r1"."staging"."stg_fact_ledger"
where quantity < 1 or quantity > 999
  
  
      
    ) dbt_internal_test