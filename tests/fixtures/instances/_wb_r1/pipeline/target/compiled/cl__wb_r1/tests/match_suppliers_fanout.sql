
-- 匹配契约：suppliers 的键 supplier_code 必须唯一，否则 join 扇出/笛卡尔积
select supplier_code
from "_wb_r1"."staging"."stg_suppliers"
group by 1 having count(*) > 1