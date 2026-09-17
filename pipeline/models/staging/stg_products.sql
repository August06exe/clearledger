-- 商品主数据 · 清洗层
with src as (
    select * from {{ source('raw', 'products') }}
)
select
    trim(product_id)                as product_id,
    trim(product_name)              as product_name,
    trim(category)                  as category,
    trim(unit)                      as unit,
    cast(std_price as decimal(18, 2)) as std_price,
    cast(std_cost as decimal(18, 2))  as std_cost
from src
where product_id is not null
