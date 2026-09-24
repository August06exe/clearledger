
-- 字段契约：折扣率 范围 [0, 1]
select discount_rate
from "_wb_r1"."staging"."stg_fact_ledger"
where discount_rate < 0 or discount_rate > 1