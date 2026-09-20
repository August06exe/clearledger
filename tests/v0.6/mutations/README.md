# 变异体装备校正（设计文档 §7）

三个已知 bug 的副本注入，验证测试装备"见过红灯"。**真实仓库零改动**。

| id | bug 类 | 装备必须抓 |
|---|---|---|
| M1 | 保存绕过校验 | B-保存非法草稿：期望 422 不落盘，变异体却 200 落盘 → caught |
| M2 | 挂起队列丢级 | W-挂起投影与密封答案比对：缺 yellow 行 → caught |
| M3 | 白名单/防穿越失效 | B-非白名单404 / B-穿越拒绝 → caught |

流程（测试 Agent 按此执行，详见 TESTPLAN 变异节）：
1. `python tests/v0.6/mutations/apply_mutation.py M1` → 按提示起 8630 副本服务
2. 对 8630 跑对应的探针 Case（与正式 Case 相同的命令，换端口）
3. 结果记 `behaviors_round<N>.json`：`{id: "MUT-M1", expect: "caught", observed: "caught|survived", evidence}`
4. `rm -rf build/_mut_M1` 恢复；依次 M2、M3
5. 三个全部 caught = 装备校正通过；任何 survived 记入 SCOREBOARD 债务并停止判分
