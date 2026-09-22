-- 生成物：勾稽守恒测试（contribution_dept ← contribution_project；比率/非可加指标豁免）
with child as (
  select "月份", "一级部门", "责任贡献"
  from {{ ref('mart_contribution_dept') }}
), parent as (
  select "月份", "一级部门", round(sum(revenue_amt) + sum(amort_rev) + sum(subsidy) - sum(salary) - sum(social_ins) - sum(recruit_fee) - sum(travel_fee) - sum(expense_fee) - sum(platform_fee) - sum(levy), 2) as "责任贡献"
  from {{ ref('mart_contribution_project') }}
  group by 1, 2
)
select '责任贡献' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."一级部门", c."一级部门") as "一级部门", p."责任贡献" as 父层重算, c."责任贡献" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."一级部门" = c."一级部门" or (p."一级部门" is null and c."一级部门" is null)) where abs(coalesce(p."责任贡献", 0) - coalesce(c."责任贡献", 0)) > 0.01
