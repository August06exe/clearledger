
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
-- 字段契约：期末数量 范围 [0, 100000]
select ending_qty
from "_wb_r1"."staging"."stg_stock_snapshot"
where ending_qty < 0 or ending_qty > 100000
  
  
      
    ) dbt_internal_test