# UPGRADE.md — 逐版本升级须知

单文件逐版本追加，只加不改：每个 Release 发版前由维护者填好当节，没写当节的版本不许发 tag（四件资产同版本：产品 zip、upgrade-manifest.json、本文件当节、launcher 有变更时的 exe）。旧节的文字保持原样，勘误在当节之下补记。

agent 的解读顺序（方案 6.3）：先 upgrade-manifest.json（定流程分支——走哪条通道、要不要金丝雀、能不能自动升、契约变没变），再本文件（定人工项与哨兵），最后 Release notes 正文（背景）。manifest 模板在仓库根 `upgrade-manifest.example.json`，字段名与类型以 `ops/upgrade.py` 的校验器为准。

命令行以 `ops/upgrade.py --help` 与 docs/02-操作手册.md R-14 为准（R-14 是完整 SOP，含通道判定与失败出口）；本文件只承载逐版本的差异信息。

## 协议现状（2026-09-30，P0 骨架——以代码为准）

`ops/upgrade.py` 已实现 plan / preflight / status / stop / backup（含哨兵基线）/ migrate / switch / sync / canary / smoke / rollback / finalize / prune。四条边界，升级时绕开而不是等：

1. `stage` 是占位（exit 3）：下载、解压、sha256 比对、builtin yml diff 尚未自动化。通道 Z 的 staging 一律用下方首次自举的两条引导命令手工产出，sha256 与 builtin diff 手工做（命令见 R-14），stage 子命令不要调用。
2. `refresh` 无独立子命令：依赖核对并入了 smoke，强制 `pip install -r requirements.txt` 由手册承担——版本移动之后、canary/smoke 之前手动跑一遍（R-14 序列已排入）。
3. `finalize` 不代跑正式三步链与人类验收：记账、VERSION 与 ?v= 复核、快照清单提示之后，按 AGENTS.md 快速命令逐账套跑三步链，人在门户验收，验收不过走 rollback（finalize 之后回滚必走情形 B——三步链已写过真实库）。
4. 关窗统一走 prune（两通道共用）：通道 G 跳过 prev 收敛（无 prev 槽位，版本移动走 git），只列示升级快照并清 in_progress；通道 Z 额外把 prev 收敛到最近两代。验收通过后跑 `py -3 R\ops\upgrade.py prune` 即关窗（prune 之后不可再 rollback），不要手改 `data/upgrade/state.json`。

## 首次自举（现场还没有 ops/upgrade.py 的环境，每台机器一次性）

目标版本记为 v0.6.1（换成实际 tag），产品根记为 R，解包产物记为 S（`upgrade\staging-v0.6.1`）。两条引导命令只有下载与解压，无取舍判断；zip 资产名以 Release 资产页实际为准（下方 URL 是占位示例，make_release.py 出包器落地前资产名未定）：

```
powershell -NoProfile -Command "Invoke-WebRequest -Uri https://github.com/August06exe/clearledger/releases/download/v0.6.1/clearledger-v0.6.1.zip -OutFile upgrade\v0.6.1.zip"
powershell -NoProfile -Command "Expand-Archive -Path upgrade\v0.6.1.zip -DestinationPath upgrade\staging-v0.6.1"
powershell -NoProfile -Command "Get-FileHash -Algorithm SHA256 upgrade\v0.6.1.zip"
```

第三条取哈希与 Release 的 upgrade-manifest.json 里 zip_sha256 人工比对（比不过就停，删掉 zip 重下）。脚本真正落位到产品根发生在 switch 的 rename，此前 R 内没有 ops\upgrade.py，所以从 plan 到 migrate 全部用 S 内脚本加 `--root R`（注意 `--root` 必须写在子命令之前）：

```
R\.venv\Scripts\python.exe S\ops\upgrade.py --root R plan --target v0.6.1
R\.venv\Scripts\python.exe S\ops\upgrade.py --root R preflight --target v0.6.1
# （人类拍板后继续）
R\.venv\Scripts\python.exe S\ops\upgrade.py --root R stop
R\.venv\Scripts\python.exe S\ops\upgrade.py --root R backup
py -3 S\ops\upgrade.py --root R migrate
py -3 S\ops\upgrade.py --root R switch
```

switch 把 S 换名为 R 后，从依赖刷新起回到通道 Z 主序列（R-14），用产品根自己的脚本执行。

## 每版一节的格式（发版时按此追加）

每节必含四块：口径变更表（哪个报表哪个数字为什么变）、requires_manual_steps 的展开（manifest 里只有一行，这里写成人能执行的步骤）、金丝雀哨兵清单（每张报表一条取数命令，升级前后各跑一遍比对数字）、回滚特别注意（本版有没有让回滚变复杂的点）。以下首节是实例也是格式样板。

## v0.6.1（首个带升级协议的版本——发版前把本节示例值换成实值）

- 口径变更：无。本版只加升级安全基建（VERSION 单一出处、ops/upgrade.py、ops/backup.py、doctor 升级面体检），不改任何账套口径，不动物理表结构。报表数字若与本节哨兵基线不一致，一律按异常分诊，不是本版预期变化。
- requires_manual_steps：无（manifest.requires_manual_steps=[]）。通道 Z 现场的 staging 产出与 sha256 比对属手工动作（协议现状第 1 条），不列人工确认项。
- 金丝雀哨兵清单（mart_schema_changed=false，本版金丝雀跳过；哨兵取数命令留档，供 smoke 的真库比对与人工复核）：
  - sales / region_month：`R\.venv\Scripts\python.exe -m semantic.query sales region_month`
  - 餐饮与其他账套本版无报表改动，升级后红绿灯基线不变即可（sales 37 / restaurant 27 / retail 70 / hro 56 / ladder 61 节点）。
- 回滚特别注意：`py -3 R\ops\upgrade.py rollback`。本版是升级协议首版，从 v0.6.0 升上来的现场回滚目标即 v0.6.0；通道 Z 首升现场注意 prev 槽位是 switch 时才生成的（v0.6.0 整目录换名而来），rollback 前不要手删 `upgrade\prev-v0.6.0`。finalize 之后回滚必走情形 B（先恢复快照再换版本），属正常路径不是故障。
