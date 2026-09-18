-- 生成物：staging 清洗模型（来源 instances 配置，勿手改）
select
    trim(cast(dish_code as varchar)) as dish_code,
    trim(cast(dish_name as varchar)) as dish_name,
    trim(cast(dish_cat as varchar)) as dish_cat,
    cast(std_cost as decimal(18, 4)) as std_cost
from {{ source('raw', 'dishes') }}
where dish_code is not null
