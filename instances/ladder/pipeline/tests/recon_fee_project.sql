-- 生成物：勾稽守恒测试（fee_project ← revenue_project；比率/非可加指标豁免）
with child as (
  select "月份", "项目", "商旅费", "费用报销", "平台管理费", "残保金", "期间费用合计"
  from {{ ref('mart_fee_project') }}
), parent as (
  select "月份", "项目", sum(travel_fee) as "商旅费", sum(expense_fee) as "费用报销", sum(platform_fee) as "平台管理费", sum(levy) as "残保金", round(sum(travel_fee) + sum(expense_fee) + sum(platform_fee) + sum(levy), 2) as "期间费用合计"
  from {{ ref('mart_revenue_project') }}
  group by 1, 2
)
select '商旅费' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", p."商旅费" as 父层重算, c."商旅费" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) where abs(coalesce(p."商旅费", 0) - coalesce(c."商旅费", 0)) > 0.01
union all
select '费用报销' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", p."费用报销" as 父层重算, c."费用报销" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) where abs(coalesce(p."费用报销", 0) - coalesce(c."费用报销", 0)) > 0.01
union all
select '平台管理费' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", p."平台管理费" as 父层重算, c."平台管理费" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) where abs(coalesce(p."平台管理费", 0) - coalesce(c."平台管理费", 0)) > 0.01
union all
select '残保金' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", p."残保金" as 父层重算, c."残保金" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) where abs(coalesce(p."残保金", 0) - coalesce(c."残保金", 0)) > 0.01
union all
select '期间费用合计' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", p."期间费用合计" as 父层重算, c."期间费用合计" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) where abs(coalesce(p."期间费用合计", 0) - coalesce(c."期间费用合计", 0)) > 0.01
