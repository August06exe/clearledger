{{ config(severity='error') }}
-- 匹配契约：subsidy_policies 的键 policy_code 必须唯一，否则 join 扇出/笛卡尔积
select policy_code
from {{ ref('stg_subsidy_policies') }}
group by 1 having count(*) > 1
