{{ config(severity='warn') }}
-- 字段契约：月薪资成本 范围 [0, 100000]
select salary_cost
from {{ ref('stg_roster') }}
where salary_cost < 0 or salary_cost > 100000
