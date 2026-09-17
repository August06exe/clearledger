-- 月 × 区域 组合必须唯一（报表层粒度完整性）
select
    month,
    region_code,
    count(*) as n
from {{ ref('mart_region_month') }}
group by 1, 2
having count(*) > 1
