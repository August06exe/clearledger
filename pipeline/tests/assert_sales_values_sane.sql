{{ config(severity='warn') }}
-- 黄灯规则：流水数值合理性——正数量、无未来订单、非负收入
select
    order_id,
    quantity,
    order_date,
    net_amount
from {{ ref('int_sales_enriched') }}
where quantity <= 0
   or order_date > current_date
   or net_amount < 0
