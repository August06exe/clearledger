
    

    create  table
      "_wb_r1"."marts"."mart_supplier_rank__dbt_tmp"
  
    
    as (
      -- 生成物：报表汇总模型（供应商采购排行 = 维度×指标）
select
supplier_name as "供应商",
    sum(purchase_amt) as "采购额"
from "_wb_r1"."intermediate"."int_wide_ledger"
group by 1
    );
    
  