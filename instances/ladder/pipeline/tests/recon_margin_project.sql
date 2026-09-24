-- 生成物：勾稽守恒测试（margin_project ← revenue_project；比率/非可加指标豁免）
with child as (
  select "月份", "项目", "一级部门", "工资奖金", "社保公积金", "招聘费", "人力成本", "毛利"
  from {{ ref('mart_margin_project') }}
), parent as (
  select "月份", "项目", "一级部门", sum(salary) as "工资奖金", sum(social_ins) as "社保公积金", sum(recruit_fee) as "招聘费", + (sum(salary))+ (sum(social_ins))+ (sum(recruit_fee)) as "人力成本", + (sum(revenue_amt))+ (sum(amort_rev))- (+ (sum(salary))+ (sum(social_ins))+ (sum(recruit_fee))) as "毛利"
  from {{ ref('mart_revenue_project') }}
  group by 1, 2, 3
)
select '工资奖金' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", coalesce(p."一级部门", c."一级部门") as "一级部门", p."工资奖金" as 父层重算, c."工资奖金" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) and (p."一级部门" = c."一级部门" or (p."一级部门" is null and c."一级部门" is null)) where abs(coalesce(p."工资奖金", 0) - coalesce(c."工资奖金", 0)) > 0.01
union all
select '社保公积金' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", coalesce(p."一级部门", c."一级部门") as "一级部门", p."社保公积金" as 父层重算, c."社保公积金" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) and (p."一级部门" = c."一级部门" or (p."一级部门" is null and c."一级部门" is null)) where abs(coalesce(p."社保公积金", 0) - coalesce(c."社保公积金", 0)) > 0.01
union all
select '招聘费' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", coalesce(p."一级部门", c."一级部门") as "一级部门", p."招聘费" as 父层重算, c."招聘费" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) and (p."一级部门" = c."一级部门" or (p."一级部门" is null and c."一级部门" is null)) where abs(coalesce(p."招聘费", 0) - coalesce(c."招聘费", 0)) > 0.01
union all
select '人力成本' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", coalesce(p."一级部门", c."一级部门") as "一级部门", p."人力成本" as 父层重算, c."人力成本" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) and (p."一级部门" = c."一级部门" or (p."一级部门" is null and c."一级部门" is null)) where abs(coalesce(p."人力成本", 0) - coalesce(c."人力成本", 0)) > 0.01
union all
select '毛利' as 指标, coalesce(p."月份", c."月份") as "月份", coalesce(p."项目", c."项目") as "项目", coalesce(p."一级部门", c."一级部门") as "一级部门", p."毛利" as 父层重算, c."毛利" as 子层值 from parent p full outer join child c on (p."月份" = c."月份" or (p."月份" is null and c."月份" is null)) and (p."项目" = c."项目" or (p."项目" is null and c."项目" is null)) and (p."一级部门" = c."一级部门" or (p."一级部门" is null and c."一级部门" is null)) where abs(coalesce(p."毛利", 0) - coalesce(c."毛利", 0)) > 0.01
