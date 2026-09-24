
-- 字段契约：期末数量 范围 [0, 1000000]
select ending_qty
from "_wb_r1"."staging"."stg_fact_ledger"
where ending_qty < 0 or ending_qty > 1000000