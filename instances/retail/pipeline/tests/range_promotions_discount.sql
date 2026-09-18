{{ config(severity='warn') }}
-- 字段契约：折扣力度 范围 [0, 0.5]
select discount
from {{ ref('stg_promotions') }}
where discount < 0 or discount > 0.5
