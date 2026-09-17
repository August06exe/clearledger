-- 部门费用 · 加工层：费用分摊
--
-- 分摊规则（唯一出处）：
--   1. 销售事业部费用 → 直接归属其负责区域
--   2. 总部/职能部门费用 → 按各区域当月收入占比分摊到区域
-- 输出粒度：月 × 部门 × 费用类别 × 区域
--   expense_amount   = 部门原始费用（在分摊行上会按区域重复出现，仅供溯源）
--   allocated_amount = 分摊到该区域的金额（口径：净利 = 区域毛利 − 区域分摊费用）
with sales_region_month as (
    select
        date_trunc('month', order_date) as month,
        region_code,
        sum(net_amount) as revenue
    from {{ ref('int_sales_enriched') }}
    group by 1, 2
),
region_month_total as (
    select month, sum(revenue) as total_revenue
    from sales_region_month
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
    -- 总部/职能费用：按当月各区域收入占比分摊
    select
        date_trunc('month', e.expense_date) as month,
        e.dept_code,
        e.dept_name,
        e.category,
        r.region_code,
        e.amount as expense_amount,
        round(e.amount * r.revenue / t.total_revenue, 2) as allocated_amount
    from expenses_tagged e
    join sales_region_month r
        on date_trunc('month', e.expense_date) = r.month
    join region_month_total t
        on t.month = r.month
    where e.is_sales_dept = 0
)
select month, dept_code, dept_name, category, region_code, expense_amount, allocated_amount from direct
union all
select month, dept_code, dept_name, category, region_code, expense_amount, allocated_amount from shared
