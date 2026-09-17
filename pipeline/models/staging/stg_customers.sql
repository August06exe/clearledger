-- 客户主数据 · 清洗层
-- 清洗规则：编号/名称去首尾空格；状态规整为 {活跃, 流失}
with src as (
    select * from {{ source('raw', 'customers') }}
)
select
    trim(customer_id)   as customer_id,
    trim(customer_name) as customer_name,
    trim(industry)      as industry,
    trim(level)         as customer_level,
    trim(region_code)   as region_code,
    trim(region_name)   as region_name,
    case trim(status)
        when '活跃' then '活跃'
        when '流失' then '流失'
        else '未知'
    end                 as status
from src
where customer_id is not null
