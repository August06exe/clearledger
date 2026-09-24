
-- 字段契约：数量 范围 [1, 999]
select quantity
from "_wb_r1"."staging"."stg_fact_ledger"
where quantity < 1 or quantity > 999