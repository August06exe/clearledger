-- 生成物：勾稽守恒测试（group_pnl ← contribution_dept；比率/非可加指标豁免）
with child as (
  select "月份", "集团净利"
  from {{ ref('mart_group_pnl') }}
), parent as (
  select "月份", + (+ (sum(revenue_amt))+ (sum(amort_rev))+ (sum(subsidy))- (+ (sum(salary))+ (sum(social_ins))+ (sum(recruit_fee)))- (+ (sum(travel_fee))+ (sum(expense_fee))+ (sum(platform_fee))+ (sum(levy))))- (sum(group_fee)) as "集团净利"
  from {{ ref('mart_contribution_dept') }}
  group by 1
)
select '集团净利' as 指标, coalesce(p."月份", c."月份") as "月份", p."集团净利" as 父层重算, c."集团净利" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) where abs(coalesce(p."集团净利", 0) - coalesce(c."集团净利", 0)) > 0.01
