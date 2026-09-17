-- 销售事业部必须声明负责区域：
-- 否则其费用在"直接归属"时会落到 NULL 区域，区域报表静默丢费用（区域合计对不平公司合计）
select
    dept_code,
    dept_name
from {{ ref('stg_org') }}
where is_sales_dept = 1
  and region_code is null
