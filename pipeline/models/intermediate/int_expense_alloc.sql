-- 部门费用 · 加工层：费用分摊
--
-- 分摊规则（唯一出处）：
--   1. 销售事业部费用 → 直接归属其负责区域
--   2. 总部/职能部门费用 → 按各区域当月收入占比分摊到区域；
--      该月全公司零收入时按区域数均摊（兜底：总部费用绝不允许静默蒸发）
-- 输出粒度：月 × 部门 × 费用类别 × 区域
--   expense_amount   = 部门原始费用（在分摊行上按区域重复出现，仅供溯源，不可直接汇总）
--   allocated_amount = 分摊到该区域的金额（口径：净利 = 区域毛利 − 区域分摊费用）
with months as (
    select distinct date_trunc('month', expense_date) as month
    from {{ ref('stg_expenses') }}
),
regions as (
    select distinct region_code
    from {{ ref('stg_customers') }}
    where region_code is not null
),
month_regions as (
    select m.month, r.region_code
    from months m
    cross join regions r
),
sales_region_month as (
    select
        date_trunc('month', order_date) as month,
        region_code,
        sum(net_amount) as revenue
    from {{ ref('int_sales_enriched') }}
    group by 1, 2
),
revenue_base as (
    -- 月 × 区域收入骨架（某区域当月无销售则补 0，保证分摊比率完整）
    select
        mr.month,
        mr.region_code,
        coalesce(s.revenue, 0) as revenue
    from month_regions mr
    left join sales_region_month s
        on s.month = mr.month
       and s.region_code = mr.region_code
),
revenue_total as (
    select month, sum(revenue) as total_revenue, count(*) as region_cnt
    from revenue_base
    group by 1
),
expenses_tagged as (
    select
        e.*,
        o.is_sales_dept,
        o.region_code as owner_region_code
    from {{ ref('stg_expenses') }} e
    join {{ ref('stg_org') }} o on e.dept_code = o.dept_code
),
direct as (
    -- 事业部费用：直接归属
    select
        date_trunc('month', expense_date) as month,
        dept_code,
        dept_name,
        category,
        owner_region_code as region_code,
        amount as expense_amount,
        amount as allocated_amount
    from expenses_tagged
    where is_sales_dept = 1
),
shared as (
    -- 总部/职能费用：收入占比分摊；零收入月按区域数均摊
    select
        date_trunc('month', e.expense_date) as month,
        e.dept_code,
        e.dept_name,
        e.category,
        rb.region_code,
        e.amount as expense_amount,
        case
            when t.total_revenue > 0
                then round(e.amount * rb.revenue / t.total_revenue, 2)
            else round(e.amount * 1.0 / t.region_cnt, 2)
        end as allocated_amount
    from expenses_tagged e
    join revenue_base rb
        on date_trunc('month', e.expense_date) = rb.month
    join revenue_total t
        on t.month = rb.month
    where e.is_sales_dept = 0
)
select month, dept_code, dept_name, category, region_code, expense_amount, allocated_amount from direct
union all
select month, dept_code, dept_name, category, region_code, expense_amount, allocated_amount from shared
