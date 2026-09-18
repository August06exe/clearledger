
-- 匹配契约：dishes 的键 dish_code 必须唯一，否则 join 扇出/笛卡尔积
select dish_code
from "restaurant"."staging"."stg_dishes"
group by 1 having count(*) > 1