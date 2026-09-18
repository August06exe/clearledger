{{ config(severity='warn') }}
-- 字段契约：期末数量 范围 [0, 1000000]
select ending_qty
from {{ ref('stg_stock_snapshots') }}
where ending_qty < 0 or ending_qty > 1000000
