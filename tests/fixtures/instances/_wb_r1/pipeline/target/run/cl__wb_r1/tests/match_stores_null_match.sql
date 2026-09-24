
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
-- 匹配契约：主表 store_code 在 stores 中匹空的清单（未匹配标签）
select distinct w.store_code
from "_wb_r1"."intermediate"."int_wide_ledger" w
where w.store_code is not null
  and not exists (
    select 1 from "_wb_r1"."staging"."stg_stores" d
    where d.store_code = w.store_code)
  
  
      
    ) dbt_internal_test