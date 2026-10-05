# tests/ —— 测试

- `upgrade/` — 无损升级功能的日常测试：84 个单元测试 + 沙盘全链演练脚本 `drill_p0.py`（改了升级代码就跑）
- `fixtures/` — 测试夹具账套（含 `_wb_r1`）
- `v0.4/` `v0.5/` `v0.6/` — **三权分立密封考卷**：命题/测试/评审三个独立 AI 的验收产物，含密封答案。属于冻结证据，任何情况下不许改内容（历史教训与规则见 AGENTS.md 红线）

跑升级测试：`.venv/Scripts/python.exe -m unittest discover -s tests/upgrade`
