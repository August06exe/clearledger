
    

    create  table
      "restaurant"."marts"."mart_channel_month__dbt_tmp"
  
    
    as (
      -- 生成物：报表汇总模型（渠道月报 = 维度×指标）
select
date_trunc('month', order_time) as "月份",
channel as "渠道",
    sum(amount) as "营业额",
    sum(gross_profit) as "毛利"
from "restaurant"."intermediate"."int_wide_orders"
where date_trunc('month', order_time) < date_trunc('month', current_date)
group by 1, 2
    );
    
  