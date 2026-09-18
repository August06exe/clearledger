
    

    create  table
      "restaurant"."marts"."mart_monthly_kpi__dbt_tmp"
  
    
    as (
      -- 生成物：报表汇总模型（经营月报（公司级） = 维度×指标）
select
date_trunc('month', order_time) as "月份",
    sum(amount) as "营业额",
    sum(gross_profit) as "毛利",
    round(sum(gross_profit) / nullif(sum(amount), 0), 4) as "毛利率",
    count(distinct order_no) as "客单数"
from "restaurant"."intermediate"."int_wide_orders"
where date_trunc('month', order_time) < date_trunc('month', current_date)
group by 1
    );
    
  