
-- 匹配契约：主表 customer_id 在 customers 中匹空的清单（未匹配标签）
select distinct m.customer_id
from "sales"."staging"."stg_sales_transactions" m
left join "sales"."staging"."stg_customers" d on m.customer_id = d.customer_id
where m.customer_id is not null and d.customer_id is null