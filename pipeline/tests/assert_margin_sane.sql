{{ config(severity='warn') }}
-- 黄灯规则：公司毛利率超出 [0, 1] 合理区间 → 口径或数据异常提醒
select
    month,
    gross_margin
from {{ ref('mart_kpi_monthly') }}
where gross_margin is not null
  and (gross_margin < 0 or gross_margin > 1)
