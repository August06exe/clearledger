-- 销售流水 · 加工层：关联客户标签与商品主数据，派生全公司唯一的金额口径
--
-- 口径（唯一出处，报表层只能引用、不得重算）：
--   折后金额 net_amount  = 订单金额 × (1 − 折扣率)
--   成本金额 cost_amount = 数量 × 商品标准成本
--   毛利    gross_profit = 折后金额 − 成本金额
with s as (
    select * from {{ ref('stg_sales') }}
),
c as (
    select * from {{ ref('stg_customers') }}
),
p as (
    select * from {{ ref('stg_products') }}
)
select
    s.order_id,
    s.order_date,
    s.customer_id,
    c.customer_name,
    c.industry,
    c.customer_level,
    c.region_code,
    c.region_name,
    c.status as customer_status,
    s.product_id,
    p.product_name,
    p.category,
    s.quantity,
    s.unit_price,
    s.discount_rate,
    s.amount as gross_amount,
    round(s.amount * (1 - s.discount_rate), 2) as net_amount,
    round(s.quantity * p.std_cost, 2) as cost_amount,
    round(s.amount * (1 - s.discount_rate) - s.quantity * p.std_cost, 2) as gross_profit
from s
join c on s.customer_id = c.customer_id
join p on s.product_id = p.product_id
