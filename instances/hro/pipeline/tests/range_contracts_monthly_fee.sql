{{ config(severity='warn') }}
-- 字段契约：月服务费 范围 [1000, 100000]
select monthly_fee
from {{ ref('stg_contracts') }}
where monthly_fee < 1000 or monthly_fee > 100000
