{{ config(severity='warn') }}
-- 黄灯规则：区域收入环比骤降 > 50% 触发数据质量告警（不阻断发布）
-- 注：排除未走完的当前自然月，避免"月份还没跑完"的假告警
select
    month,
    region_name,
    revenue,
    revenue_mom
from {{ ref('mart_region_month') }}
where revenue_mom is not null
  and revenue_mom < -0.5
  and month < date_trunc('month', current_date)
