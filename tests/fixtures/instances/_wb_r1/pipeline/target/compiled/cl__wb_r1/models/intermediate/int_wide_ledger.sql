-- 生成物：宽表装配（fact_ledger + 3 张标签表有序左联 + 派生列）
select
    m.entry_type,
    m.doc_no,
    m.doc_date,
    m.store_code,
    m.product_code,
    m.supplier_code,
    m.channel,
    m.quantity,
    m.unit_price,
    m.discount_rate,
    m.ending_qty,
    d0.store_name,
    d0.city,
    d0.region_name,
    d1.product_name,
    d1.category,
    d1.std_cost,
    d2.supplier_name,
    case when entry_type = '销售' then round(quantity * unit_price * (1 - discount_rate), 2) else 0 end as "sales_net",
    case when entry_type = '销售' then round(quantity * std_cost, 2) else 0 end as "sales_cost",
    case when entry_type = '销售' then round(quantity * unit_price * (1 - discount_rate) - quantity * std_cost, 2) else 0 end as "gross_profit",
    case when entry_type = '销售' and channel = '电商' then round(quantity * unit_price * (1 - discount_rate), 2) else 0 end as "ecomm_net",
    case when entry_type = '采购' then round(quantity * unit_price, 2) else 0 end as "purchase_amt",
    case when entry_type = '期末库存' then coalesce(ending_qty, 0) else 0 end as "stock_qty"
from "_wb_r1"."staging"."stg_fact_ledger" m
left join "_wb_r1"."staging"."stg_stores" d0
  on m.store_code = d0.store_code
left join "_wb_r1"."staging"."stg_products" d1
  on m.product_code = d1.product_code
left join "_wb_r1"."staging"."stg_suppliers" d2
  on m.supplier_code = d2.supplier_code