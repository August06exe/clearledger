-- 销售流水 · 清洗层
-- 清洗规则：trim 关键字段；日期取日期部分；金额/数量强类型化；
--           折扣率缺失视为无折扣（补 0）；剔除无订单号/无日期的坏行
with src as (
    select * from {{ source('raw', 'sales_transactions') }}
)
select
    trim(order_id)                          as order_id,
    cast(order_date as date)                as order_date,
    trim(customer_id)                       as customer_id,
    trim(product_id)                        as product_id,
    cast(quantity as bigint)                as quantity,
    cast(unit_price as decimal(18, 2))      as unit_price,
    coalesce(cast(discount_rate as decimal(6, 4)), 0) as discount_rate,
    cast(amount as decimal(18, 2))          as amount,
    _source_file,
    cast(_loaded_at as timestamp)           as loaded_at
from src
where order_id is not null
  and order_date is not null
