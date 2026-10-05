# instances/ —— 账套

一个公司（或一套业务）一个子文件夹，互不串门，各有独立数据库。

| 账套 | 内容 |
| --- | --- |
| sales | 演示销售公司 |
| restaurant | 演示连锁餐饮 |
| retail / hro | 测试用：零售进销存 / 人力外包 |
| ladder | 演示：集团经营核算·利润阶梯（报表分层） |

每个账套内：

- 六份 yml（instance/sources/wide/dimensions/metrics/dashboard）＝六份配方，**指标口径只认这里的 metrics.yml**
- `data/inbox/` ＝ 收货口，每月的 Excel/CSV 丢进来
- `pipeline/` ＝ 由配方自动生成的 dbt 车间，**禁手改**（要改就改 yml 再重新编译）
- `onboarding/config_history/` ＝ 配置工作台的滚动备份（运行痕迹，不入 git）

下划线开头的账套（如 `_wb_r1`）是测试专用，不进正式清单。
