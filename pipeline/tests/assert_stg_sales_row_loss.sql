{{ config(severity='warn') }}
-- 黄灯规则：清洗层剔行对账——坏行剔除超过 1% 说明源文件质量恶化，
-- 防止 stg_sales 静默丢弃坏行导致收入悄悄缩水
with raw_cnt as (
    select count(*) as n from {{ source('raw', 'sales_transactions') }}
),
stg_cnt as (
    select count(*) as n from {{ ref('stg_sales') }}
)
select
    raw_cnt.n as raw_rows,
    stg_cnt.n as stg_rows
from raw_cnt, stg_cnt
where stg_cnt.n < raw_cnt.n * 0.99
