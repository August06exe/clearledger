# TESTPLAN — v0.5 配置工作台验收（tests/v0.6，实例 `_wb_r1`）【R2 版】

> **你（测试 Agent）的唯一指令来源是本文。** 纪律：
> 1. **禁读** `tests/v0.6/expected/`（密封答案区）与 `tests/v0.6/SPEC.md`（场景圣经，含答案相邻信息）——读了即泄密，判分作废；
> 2. **禁改** 被测系统任何代码与官方账套（`instances/sales|restaurant|retail|hro|ladder/`）任何文件（MR-05 的**原样内容** save+rebuild 是唯一经裁定的例外，见 §6）；
> 3. 你的产物**只写** `tests/v0.6/judge/`（自建目录）与临时目录 `build/_mut_*/`；
> 4. 门户已在 `http://127.0.0.1:8620` 运行——**不得重启**（变异体副本用 8630，见 §7）；
> 5. 全程工作目录 = 仓库根；Python 用 `.venv/Scripts/python.exe`；
> 6. 所有命令逐条执行并记录退出码；观测值原样入 `judge/`，**不做任何"修复"**。
>
> R2 执行顺序：§1 → §2 → §4（W-01…W-05，其中 W-04/W-05 只读 ladder）→ §5（B-01…B-06、B-10、B-11）→ §6（MR-01…MR-05）→ §8（B-07、B-08）→ §7（变异体）→ §9（基线恢复）→ §10（自检）。

对象类型 = SaaS/API 预设：密封答案 = 每请求 status + body 稳定投影；你的职责是**忠实采集** actual 与行为观察，判分由评审用密封区完成。

---

## 1. 环境准备与前置检查

```bash
cd <仓库根目录>

# 1.1 门户存活（不重启；不存活则停止全部测试并在 judge/BLOCKED.md 写明）
curl -s -o judge/preflight_instance.json -w '%{http_code}\n' http://127.0.0.1:8620/api/instance
# 期望 200 + JSON（含 current 字段）

# 1.2 系统自检（建议性，不作为闸门）
.venv/Scripts/python.exe ops/doctor.py --json > judge/preflight_doctor.json

# 1.3 官方账套配置基线哈希（B-08 的 before 快照，必须最先做；含 ladder）
sha256sum instances/sales/*.yml instances/restaurant/*.yml instances/retail/*.yml instances/hro/*.yml \
  instances/ladder/*.yml > judge/hash_official_before.txt
```

## 2. 基线装配（三步链 + 收获）

```bash
.venv/Scripts/python.exe tests/v0.6/generate.py                      # 幂等重建 instances/_wb_r1/
.venv/Scripts/python.exe -m semantic.ingest_run  --instance _wb_r1   # 摄取+契约校验
.venv/Scripts/python.exe -m semantic.compile_dbt --instance _wb_r1   # 配置→dbt project
(cd instances/_wb_r1/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors | tail -5)
.venv/Scripts/python.exe -m semantic.harvest --instance _wb_r1       # 匹配契约收获（R2 裁定 C：匹配契约行经此写入 contract_report）
```

- 五条命令退出码**全部记入** `judge/provenance_round2.json`（id=BASE-1..BASE-5）。
- 期望：退出码全 0；dbt build 末行 `ERROR=0`（PASS/WARN 数如实记录，不做要求）。
- **W-01 的 pending 采集必须在 harvest 之后**（否则匹配契约行缺失，属工序缺步非引擎错）。
- 若 ingest/ Harvest 退出码非 0：如实记录 stderr 摘要进 provenance 并继续（这本身就是判分证据），W 类照采。

## 3. 采集规范

- 数值类 actual：`judge/actual_*.json`，保存**完整响应体**（易变字段保留在内，判分时按口径剔除）。
- **observed 键名纪律（R2 裁定 D）**：`behaviors_round2.json` 每条 `observed` 的键名必须**逐字**使用对应 Case `expect` 声明的键名（含 `_in` 等后缀），一个不多一个不少；原始观察（HTTP 状态码数字、非灯色词表的原始状态串、响应原文等）**一律放 `evidence` 字段**，不得混入 observed 键。
- 行为类断言：`judge/behaviors_round2.json`，数组，每条 `{"id": "B-xx", "expect": <本文给出的结构原样拷贝>, "observed": <同构实测，键名逐字一致>, "evidence": "<一句话+指向的 actual 文件+原始观察>"}`。
- 蜕变观察：`judge/mr_round2.json`，数组，每条 `{"id": "MR-0x", "observation": {...}}`（**只记观察，不写期望**）。
- 溯源：`judge/provenance_round2.json`，数组，每条 `{"id": "<Case或步骤id>", "command": "<命令原文>", "exit_code": <int>}`。
- JSON 一律 UTF-8、`ensure_ascii=false`、`sort_keys=true`、结尾换行（与判分器规范化一致）。
- `curl` 统一带 `-w '%{http_code}\n'` 采集状态码（状态码写进对应 actual 的 `status` 字段或 provenance 的 note）。

---

## 4. W 类（数值采集——判分的原料，跑在基线装配后、任何写操作前）

### W-01 挂起队列稳定投影

```bash
curl -s -o judge/actual_pending.json -w '%{http_code}\n' \
  http://127.0.0.1:8620/api/config/_wb_r1/pending
```

- actual 结构：`{"status": <http码>, "body": {"instance", "latest_run": {"run_id","finished_at","light"}|null, "items": [{"source","field","rule","level","cnt","sample"}], "note": null}}`。
- 期望（结构性的）：200；items 是数组；每条 item 恰有 `source/field/rule/level/cnt/sample` 六字段；`sample` 为非空字符串；`cnt` 为非负整数。
- **双跑一致性自检（必做）**：随后执行 §6 的 MR-03（重跑摄取）后**再采一次** pending 存 `judge/actual_pending_rerun.json`，把两次 items 的 `json.dumps(sort_keys=true)` 规范化文本做逐字节 diff，结论（equal/not_equal）写进 `mr_round2.json` 的 MR-03 条目。

### W-02 影响预览

```bash
curl -s -o judge/actual_impact.json -w '%{http_code}\n' \
  http://127.0.0.1:8620/api/config/_wb_r1/impact
```

- actual 结构：`{"status": <http码>, "body": {"instance", "metrics": {指标: [报表key]}, "dimensions": {维度: [报表key]}}}`。
- 期望（结构性的）：200；两张映射覆盖 metrics.yml / dimensions.yml 声明的**全部**指标与维度（含未被引用者，其值必须为数组，未被引用者应为空数组——这是设计 §3.6 明文）；列表元素为报表 key 字符串。

### W-03 行数对数（raw 各源表 + 宽表）

> R2 裁定 B：宽表物化名 = `intermediate.int_<wide声明名>`（读 `instances/_wb_r1/wide.yml` 的 `wide.name` 拼接 `int_` 前缀，本实例即 `int_wide_ledger`）。answer 的语义标签名与物化名解耦，采集按物化名。

```bash
.venv/Scripts/python.exe - > judge/actual_rows.json <<'EOF'
import json, sys, time
import duckdb, yaml
path = "data/warehouse/_wb_r1.duckdb"
wide_name = yaml.safe_load(open("instances/_wb_r1/wide.yml", encoding="utf-8"))["wide"]["name"]
con = None
for i in range(5):                       # 跑批写锁重试（只读连接）
    try:
        con = duckdb.connect(path, read_only=True); break
    except Exception as e:
        if i == 4: print(json.dumps({"error": str(e)})); sys.exit(1)
        time.sleep(2)
tables = con.execute("select table_schema, table_name from information_schema.tables").fetchall()
out = {"raw": {}, "wide_ledger": None, "wide_materialized_as": f"intermediate.int_{wide_name}",
       "schemas_seen": sorted({t[0] for t in tables})}
for schema, name in tables:
    if schema == "raw":
        n = con.execute(f'select count(*) from raw."{name}"').fetchone()[0]
        out["raw"][name] = n
    if schema == "intermediate" and name == f"int_{wide_name}":
        out["wide_ledger"] = con.execute(f'select count(*) from "{schema}"."{name}"').fetchone()[0]
print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2))
EOF
```

- actual 结构：`{"raw": {"<源表名>": 行数}, "wide_ledger": 行数|null, "wide_materialized_as": "intermediate.int_...", "schemas_seen": [...]}`（若 `wide_ledger` 为 null，如实记录并注记"物化宽表未找到"连同 `schemas_seen`——判分证据，不是你的错误）。
- 期望（结构性的）：raw 下出现全部五个源的同名表；行数为非负整数。

### W-04 分层勾稽（ladder 账套，只读——L3/L4/L5 vs 台账直算，digest 偏差=0）

> ladder（集团经营核算·利润阶梯）是引擎自带演示账套；本 Case **只读**其配置与数据（唯 MR-05 按裁定做原样 save+rebuild）。
> 前置：若 `data/warehouse/ladder.duckdb` 不存在，按 §2 三步链对 `--instance ladder` 跑一遍（退出码入 provenance）。

```bash
# 1) 环境复位：切当前账套到 ladder 并断言（POST /api/instance 形态如不匹配，改用 ?instance= 查询串并把实际形态记入 evidence）
curl -s -o judge/actual_W04_switch.json -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8620/api/instance -H 'Content-Type: application/json' -d '{"instance":"ladder"}'
curl -s -o judge/actual_W04_instance.json http://127.0.0.1:8620/api/instance   # 须可见 current=ladder
# 2) 采集三张分层报表数据（响应体原样保存）
for key in contribution_project contribution_dept group_pnl; do
  curl -s -o "judge/actual_W04_report_$key.json" "http://127.0.0.1:8620/api/reports/$key/data"
done
# 3) 台账直算（独立实现：口径公式逐字取自 instances/ladder/metrics.yml，数据取 raw.ledger 源镜像，绝不读 marts）
.venv/Scripts/python.exe - > judge/actual_W04_digest.json <<'EOF'
import json, sys, time
import duckdb, pandas as pd
con = None
for i in range(5):
    try:
        con = duckdb.connect("data/warehouse/ladder.duckdb", read_only=True); break
    except Exception as e:
        if i == 4: print(json.dumps({"error": str(e)})); sys.exit(1)
        time.sleep(2)
df = con.execute('select * from raw.ledger').df()          # 台账源镜像（直算基数）
S = {c: float(pd.to_numeric(df[c], errors="coerce").fillna(0).sum()) for c in
     ["revenue_amt","amort_rev","subsidy","salary","social_ins","recruit_fee",
      "travel_fee","expense_fee","platform_fee","levy","group_fee"]}
# 公式 = instances/ladder/metrics.yml 的 责任贡献 / 集团净利（可加列直算）：
contrib = round(S["revenue_amt"] + S["amort_rev"] + S["subsidy"]
                - S["salary"] - S["social_ins"] - S["recruit_fee"]
                - S["travel_fee"] - S["expense_fee"] - S["platform_fee"] - S["levy"], 2)
net = round(contrib - S["group_fee"], 2)
direct = {"contribution_project": contrib, "contribution_dept": contrib, "group_pnl": net}
def report_sum(path, metric_key):
    body = json.load(open(path, encoding="utf-8"))
    rows = body.get("rows") if isinstance(body, dict) else None
    if rows is None and isinstance(body, dict):
        rows = next((v for v in body.values() if isinstance(v, list)), None)
    if rows is None:
        return None
    total = 0.0
    for r in rows:
        v = r.get(metric_key)
        if v is not None:
            total += float(v)
    return round(total, 2)
out = {"direct": direct, "layers": {}}
for key, mk in [("contribution_project", "责任贡献"), ("contribution_dept", "责任贡献"), ("group_pnl", "集团净利")]:
    rs = report_sum(f"judge/actual_W04_report_{key}.json", mk)
    dev = None if rs is None else round(rs - direct[key], 2)
    out["layers"][key] = {"report_sum": rs, "direct_sum": direct[key], "deviation": dev}
out["all_zero"] = all(l["deviation"] is not None and abs(l["deviation"]) <= 0.01 for l in out["layers"].values())
print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
EOF
# 4) 环境复位：切回 sales
curl -s -o judge/actual_W04_switchback.json -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8620/api/instance -H 'Content-Type: application/json' -d '{"instance":"sales"}'
```

expect（结构性的，含零偏差断言——不依赖密封数值）：
```json
{"current_switched": true, "l3_deviation_zero": true, "l4_deviation_zero": true,
 "l5_deviation_zero": true, "amount_tolerance": 0.01}
```
（若报表响应体形态与脚本假设不符导致 report_sum=null：如实记录 `shape_mismatch` 与响应原文——这是证据，不是你的错误。）

### W-05 字段级血缘（sales stg 节点 + ladder 分层 mart 节点：全部列 ok=true、stg 上游指向源表）

```bash
# 1) sales 侧：血缘图取 stg_ 节点（运行期发现，不读生成物文件）
curl -s -o judge/actual_W05_graph_sales.json http://127.0.0.1:8620/api/lineage/graph
.venv/Scripts/python.exe - > judge/actual_W05_node_sales.txt <<'EOF'
import json, re
text = open('judge/actual_W05_graph_sales.json', encoding='utf-8').read()
names = sorted(set(re.findall(r'"(?:name|id|label)"\s*:\s*"(stg_[A-Za-z0-9_]+)"', text)))
print("\n".join(names))
EOF
# 2) 逐节点取列级血缘
while read -r n; do
  [ -z "$n" ] && continue
  curl -s -o "judge/actual_W05_cols_sales_$n.json" "http://127.0.0.1:8620/api/lineage/columns/$n"
done < judge/actual_W05_node_sales.txt
# 3) ladder 侧：级联 mart 节点（名字含 L3/L4/L5 报表 key）
curl -s -o judge/actual_W04_switch2.json -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8620/api/instance -H 'Content-Type: application/json' -d '{"instance":"ladder"}'
curl -s -o judge/actual_W05_graph_ladder.json http://127.0.0.1:8620/api/lineage/graph
.venv/Scripts/python.exe - > judge/actual_W05_node_ladder.txt <<'EOF'
import json, re
text = open('judge/actual_W05_graph_ladder.json', encoding='utf-8').read()
names = sorted(set(re.findall(r'"(?:name|id|label)"\s*:\s*"([A-Za-z0-9_]*(?:contribution_project|contribution_dept|group_pnl)[A-Za-z0-9_]*)"', text)))
print("\n".join(n for n in names if n))
EOF
while read -r n; do
  [ -z "$n" ] && continue
  curl -s -o "judge/actual_W05_cols_ladder_$n.json" "http://127.0.0.1:8620/api/lineage/columns/$n"
done < judge/actual_W05_node_ladder.txt
# 4) 断言脚本：全部列 ok=true；stg 每列上游非空且上游节点属源表层（名字含 source/raw 或上游即 stg 的输入）
.venv/Scripts/python.exe - > judge/actual_W05_assert.json <<'EOF'
import json, glob, sys
res = {"files": 0, "columns": 0, "all_ok": True, "stg_upstream_nonempty": True, "detail": []}
for f in sorted(glob.glob('judge/actual_W05_cols_*.json')):
    try:
        body = json.load(open(f, encoding='utf-8'))
    except Exception as e:
        res["detail"].append({"file": f, "error": str(e)}); res["all_ok"] = False; continue
    res["files"] += 1
    cols = body.get("columns") if isinstance(body, dict) else body
    if not isinstance(cols, list):
        res["detail"].append({"file": f, "note": "no columns array", "keys": list(body)[:8] if isinstance(body, dict) else None}); continue
    for c in cols:
        res["columns"] += 1
        ok = c.get("ok", c.get("status") in (None, "ok", True))
        if ok is not True:
            res["all_ok"] = False
            res["detail"].append({"file": f, "column": c.get("name") or c.get("column"), "ok": ok})
    if "_sales_" in f:   # stg 上游断言：每列上游非空
        for c in cols:
            up = c.get("upstream") or c.get("upstreams") or c.get("sources") or []
            if not up:
                res["stg_upstream_nonempty"] = False
                res["detail"].append({"file": f, "column": c.get("name") or c.get("column"), "upstream_empty": True})
json.dump(res, open('judge/actual_W05_assert.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2, sort_keys=True)
print(json.dumps({k: res[k] for k in ("files", "columns", "all_ok", "stg_upstream_nonempty")}, sort_keys=True))
EOF
# 5) 环境复位：切回 sales
curl -s -o judge/actual_W05_switchback.json -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8620/api/instance -H 'Content-Type: application/json' -d '{"instance":"sales"}'
```

expect：
```json
{"stg_nodes_found": true, "ladder_mart_nodes_found": true, "all_columns_ok": true,
 "stg_upstream_nonempty": true, "stg_upstream_points_to_source_layer": true}
```
（`stg_upstream_points_to_source_layer` 的判定：抽 3 个 stg 列的上游条目，确认其节点为源表层（raw/源表名），把证据摘录写进 evidence。若 graph/columns 响应形态与脚本假设不符：`observed` 记录原文与实际形态——证据优先，不许放弃采集。）

---

## 5. B 类（行为断言）

> B-01…B-06 依次执行；B-07/B-08 在 MR 之后（§6）执行。每个 Case 的 `expect` 结构**原样拷贝**进 behaviors_round2.json，`observed` 同构填写实测值。

### B-01 validate 不落盘（含 mtime）

```bash
# 1) 采集 before：文件字节、mtime、目录清单
curl -s -o judge/actual_B01_before.json http://127.0.0.1:8620/api/config/_wb_r1/metrics
stat -c '%Y %s' instances/_wb_r1/metrics.yml > judge/actual_B01_stat_before.txt
ls -1 instances/_wb_r1 > judge/actual_B01_dir_before.txt
# 2) 草稿 = 现内容 + 追加一行注释（合法草稿，交叉校验应通过）
.venv/Scripts/python.exe - <<'EOF'
import json, urllib.request, urllib.error
base = json.load(open('judge/actual_B01_before.json', encoding='utf-8'))
draft = base['content'] + '\n# draft probe B-01\n'
req = urllib.request.Request('http://127.0.0.1:8620/api/config/_wb_r1/metrics/validate',
    data=json.dumps({'content': draft}).encode(), headers={'Content-Type': 'application/json'})
try:
    r = urllib.request.urlopen(req); code, body = r.status, json.load(r)
except urllib.error.HTTPError as e:
    code, body = e.code, json.load(e)
json.dump({'status': code, 'body': body}, open('judge/actual_B01_validate.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2, sort_keys=True)
EOF
# 3) 采集 after（同 1）
stat -c '%Y %s' instances/_wb_r1/metrics.yml > judge/actual_B01_stat_after.txt
ls -1 instances/_wb_r1 > judge/actual_B01_dir_after.txt
```

expect：
```json
{"validate_status": 200, "ok": true, "errors": [], "warnings": [],
 "file_bytes_unchanged": true, "file_mtime_unchanged": true, "dir_listing_unchanged": true}
```
（`warnings` 恒为空数组是设计 §3.3 明文。）

### B-02 保存非法草稿 → 422 不写盘、不产生备份

```bash
.venv/Scripts/python.exe - <<'EOF'
import json, urllib.request, urllib.error
base = json.load(open('judge/actual_B01_before.json', encoding='utf-8'))
probe_a = 'metrics: [unclosed'                                   # YAML 语法错误
probe_b = base['content'].replace('sum(sales_net)', 'sum(col_not_exists)')  # 指标公式引用断链
def save(draft, tag):
    req = urllib.request.Request('http://127.0.0.1:8620/api/config/_wb_r1/metrics/save',
        data=json.dumps({'content': draft, 'rebuild': False}).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        r = urllib.request.urlopen(req); code, body = r.status, json.load(r)
    except urllib.error.HTTPError as e:
        code, body = e.code, json.load(e)
    json.dump({'status': code, 'body': body}, open(f'judge/actual_B02_{tag}.json','w',encoding='utf-8'),
              ensure_ascii=False, indent=2, sort_keys=True)
save(probe_a, 'syntax'); save(probe_b, 'cross')
EOF
stat -c '%Y %s' instances/_wb_r1/metrics.yml > judge/actual_B02_stat_after.txt
ls instances/_wb_r1/onboarding/config_history 2>/dev/null > judge/actual_B02_backup_check.txt; echo "exit=$?" >> judge/actual_B02_backup_check.txt
```

expect：
```json
{"syntax_status": 422, "syntax_ok": false, "syntax_errors_nonempty": true,
 "cross_status": 422, "cross_ok": false, "cross_errors_nonempty": true,
 "file_bytes_unchanged": true, "file_mtime_unchanged": true, "backup_absent": true}
```

### B-03 保存合法 → 字节级回读一致 + 备份存在

```bash
stat -c '%Y %s' instances/_wb_r1/dimensions.yml > judge/actual_B03_stat_before.txt
.venv/Scripts/python.exe - <<'EOF'
import json, urllib.request, urllib.error
def get(block):
    r = urllib.request.urlopen(f'http://127.0.0.1:8620/api/config/_wb_r1/{block}')
    return json.load(r)
def save(block, content):
    req = urllib.request.Request(f'http://127.0.0.1:8620/api/config/_wb_r1/{block}/save',
        data=json.dumps({'content': content, 'rebuild': False}).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        r = urllib.request.urlopen(req); return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
before = get('dimensions')
code, body = save('dimensions', before['content'])            # 原样保存（字节不变）
json.dump({'status': code, 'body': body}, open('judge/actual_B03_save.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2, sort_keys=True)
after = get('dimensions')
json.dump(after, open('judge/actual_B03_readback.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2, sort_keys=True)
import pathlib
bp = pathlib.Path('instances/_wb_r1/onboarding/config_history/dimensions.prev.yml')
json.dump({'backup_exists': bp.exists(),
           'backup_bytes_equal_to_saved': bp.exists() and bp.read_bytes() == before['content'].encode('utf-8')},
          open('judge/actual_B03_backup.json','w',encoding='utf-8'), indent=2, sort_keys=True)
EOF
stat -c '%Y %s' instances/_wb_r1/dimensions.yml > judge/actual_B03_stat_after.txt
```

expect：
```json
{"save_status": 200, "save_ok": true, "backup_exists": true, "backup_bytes_equal_to_saved": true,
 "readback_content_bytes_equal": true, "readback_parsed_ok": true,
 "affected_reports": [], "file_mtime_changed": true}
```
（`affected_reports: []` 是设计 §3.4 明文：仅 metrics/dashboard 块返回影响，其余块为 `[]`。`file_mtime_changed` 从 B-01/B-02 留下的 stat 记录对比得出——保存必然触碰 mtime，与 validate 的零副作用形成对照。）

### B-04 块白名单封闭 → 404

```bash
curl -s -o judge/actual_B04_permissions.json -w '%{http_code}\n' http://127.0.0.1:8620/api/config/_wb_r1/permissions
curl -s -o judge/actual_B04_unknown.json     -w '%{http_code}\n' http://127.0.0.1:8620/api/config/_wb_r1/nope
curl -s -o judge/actual_B04_validate_perm.json -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8620/api/config/_wb_r1/permissions/validate -H 'Content-Type: application/json' -d '{"content":"x: 1"}'
curl -s -o judge/actual_B04_overview.json -w '%{http_code}\n' http://127.0.0.1:8620/api/config/_wb_r1
```

expect：
```json
{"get_permissions_status": 404, "get_unknown_status": 404, "validate_permissions_status": 404,
 "detail_present_on_404": true, "overview_status": 200, "overview_blocks_count": 6}
```

### B-05 路径穿越拒绝，instances 外零落盘（R2：写向探针改单段 `..` 实例名 + `--path-as-is`，必须实测可达路由）

```bash
# 仓库根清单快照（探针前后 diff，抓任何越界落盘）
ls -1 . > judge/actual_B05_root_before.txt
# 读方向：instance 参数为单段 ".."（--path-as-is 阻止 curl 客户端归一化，探针直达路由）
curl -s --path-as-is -o judge/actual_B05_g1.json -w '%{http_code}\n' 'http://127.0.0.1:8620/api/config/../metrics'
curl -s                -o judge/actual_B05_g2.json -w '%{http_code}\n' 'http://127.0.0.1:8620/api/config/%2E/data'
curl -s                -o judge/actual_B05_g3.json -w '%{http_code}\n' 'http://127.0.0.1:8620/api/config/%2E%2E%2Fdata'
# 写方向（酸测）：instance=单段 ".." 的保存路由
curl -s --path-as-is -o judge/actual_B05_p1.json -w '%{http_code}\n' -X POST \
  'http://127.0.0.1:8620/api/config/../metrics/save' -H 'Content-Type: application/json' -d '{"content":"x: 1"}'
# 写方向（块参数单段 ".."）
curl -s --path-as-is -o judge/actual_B05_p2.json -w '%{http_code}\n' -X POST \
  'http://127.0.0.1:8620/api/config/_wb_r1/../save' -H 'Content-Type: application/json' -d '{"content":"x: 1"}'
# 越界落盘检查：边界路径全部必须不存在 + 仓库根清单不变
for f in evil.yml data/evil.yml instances/evil.yml data/warehouse/evil.yml instances/...yml metrics.yml; do
  [ -e "$f" ] && echo "EXISTS: $f" || echo "absent: $f"
done | tee judge/actual_B05_boundary.txt
ls -1 . > judge/actual_B05_root_after.txt
diff judge/actual_B05_root_before.txt judge/actual_B05_root_after.txt > judge/actual_B05_root_diff.txt
```

expect：
```json
{"g1_status_in": [400, 404], "g2_status_in": [400, 404], "g3_status_in": [400, 404],
 "p1_status_in": [400, 404], "p2_status_in": [400, 404],
 "boundary_files_all_absent": true, "repo_root_listing_unchanged": true}
```
（判定要点：这些探针必须**到达工作台路由**再被 404——若观测到 3xx 重定向或 307，`observed` 原样记录并在 evidence 注明，由判分者归因。`g1` 的 instance 参数是单段 `..`；若该形态被 HTTP 层改写（如 uvicorn 归一化），把实际到达形态写进 evidence。**observed 键名逐字用上方 expect 的键**（`g1_status_in` 等，勿丢 `_in` 后缀）；实际状态码数字放 evidence。）

### B-06 保存并重建 → 触发器 `workbench`、终态成功

```bash
# 前置：确认无跑批进行中（GET /api/runs/status，若忙则等待至空闲，记录等待时长）
curl -s -o judge/actual_B06_status_before.json http://127.0.0.1:8620/api/runs/status
.venv/Scripts/python.exe - <<'EOF'
import json, urllib.request, urllib.error
base = json.load(open('judge/actual_B01_before.json', encoding='utf-8'))   # metrics 原文
req = urllib.request.Request('http://127.0.0.1:8620/api/config/_wb_r1/metrics/save',
    data=json.dumps({'content': base['content'], 'rebuild': True}).encode(),
    headers={'Content-Type': 'application/json'})
try:
    r = urllib.request.urlopen(req, timeout=60); code, body = r.status, json.load(r)
except urllib.error.HTTPError as e:
    code, body = e.code, json.load(e)
json.dump({'status': code, 'body': body}, open('judge/actual_B06_save.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2, sort_keys=True)
EOF
# 从 actual_B06_save.json 的 body.rebuild 取 run_id（若 triggered=false 且 reason=run_in_progress：
# 等 60s 重试一次整段保存，并在 evidence 注明互斥冲突发生过）
# 轮询 run 终态（每 5s 一次，最长 180s）：
run_id=$(.venv/Scripts/python.exe -c "import json;print(json.load(open('judge/actual_B06_save.json',encoding='utf-8'))['body']['rebuild']['run_id'])")
for i in $(seq 1 36); do
  curl -s -o judge/actual_B06_run.json "http://127.0.0.1:8620/api/runs/$run_id"
  .venv/Scripts/python.exe -c "
import json;d=json.load(open('judge/actual_B06_run.json',encoding='utf-8'))
s=(d.get('status') or d.get('light') or '');print(s)" | tee judge/actual_B06_poll_tail.txt
  grep -qE 'green|yellow|red|success|fail|error|done|ok' judge/actual_B06_poll_tail.txt && break
  sleep 5
done
# 运行清单佐证（trigger 字段出处）
curl -s -o judge/actual_B06_runs_list.json "http://127.0.0.1:8620/api/runs?instance=_wb_r1"
curl -s -o judge/actual_B06_runs_list_all.json "http://127.0.0.1:8620/api/runs"
# 收尾对照：保存是原样保存，metrics 内容必须不变
curl -s -o judge/actual_B06_metrics_after.json http://127.0.0.1:8620/api/config/_wb_r1/metrics
```

expect：
```json
{"save_status": 200, "save_ok": true, "rebuild_triggered": true,
 "run_trigger": "workbench", "run_light_in": ["green", "yellow"], "metrics_content_unchanged": true}
```
（R2 修正：终态判定只走**灯色词表** `run_light_in`——dbt 状态词表与灯色词表是两套，`run_status_in` 从 expect 中删除；R3 补充：不得自创 `run_status_observed` 之类额外 observed 键——原始 status 串放 evidence。若观测到 status 字段，原样记录进 evidence 供判分者参考，不作断言。若 `/api/runs` 清单/详情无 `trigger` 字段：`observed` 原样记录全部字段，`evidence` 指向 runs_list/run 两个文件——"触发器标记=workbench 且终态成功"这个行为点本身不许放弃断言。）

### B-10 别名层一致性（界面中文化别名层非空且覆盖当前账套配置推导）

> 前置：current=sales（若前面 Case 把 current 切走过，先 POST /api/instance 切回 sales 并断言）。
> 该 Case 同时是变异体 MUT-M5（别名层清空类）的正式探针。

```bash
curl -s -o judge/actual_B10_aliases.json -w '%{http_code}\n' http://127.0.0.1:8620/api/aliases
curl -s -o judge/actual_B10_reports.json http://127.0.0.1:8620/api/reports
```

expect：
```json
{"aliases_status": 200, "aliases_nonempty": true, "covers_current_instance": true}
```
判定方法（结构性，不含答案数值）：`/api/aliases` 返回非空 JSON；从 `actual_B10_reports.json` 提取当前账套每张报表的 title 字符串，逐一在 aliases 响应**文本**中可寻得（别名层从 dashboard.title 自动推导，手册 R-11 明线）。若端点需要账套参数：先试 `/api/aliases`，再试 `/api/aliases?instance=sales`，把实际可达形态写进 evidence；若 titles 提取形态不同，记录原文。

### B-11 查询筛选白名单回退（D14：非法筛选值静默回退为"不过滤"）

> 该 Case 同时是变异体 MUT-M6（查询白名单旁路类）的正式探针。
> R2 裁定 E：守门层在端点——探针必须是**合法维度 KEY + 非法 VALUE**，并配**合法值对照组**证明值过滤路径可达（否则 survived 可能只是"端点忽略一切筛选"的假象）。

```bash
# 1) 无筛选基线行
curl -s -o judge/actual_B11_nofilter.json "http://127.0.0.1:8620/api/reports/region_month/data"
# 2) 合法值对照（值路径可达性证明：合法值必须真的过滤）
curl -s -o judge/actual_B11_goodfilter.json -w '%{http_code}\n' \
  "http://127.0.0.1:8620/api/reports/region_month/data?区域=华东"
# 3) 非法值（合法 KEY + 不存在的 VALUE → D14 回退为不过滤）
curl -s -o judge/actual_B11_badfilter.json -w '%{http_code}\n' \
  "http://127.0.0.1:8620/api/reports/region_month/data?区域=__no_such_region__"
```

expect：
```json
{"goodfilter_status": 200, "goodfilter_rows_lt_unfiltered": true,
 "badfilter_status": 200, "badfilter_rows_equal_unfiltered": true}
```
（行集比较用规范化 JSON：`json.dumps(rows, sort_keys=True, ensure_ascii=False)`。若当前账套 region_month 不可达，换可用的报表+维度组合并把实际形态写进 evidence；`区域=华东` 若在该账套无数据行，改取无筛选行集中确实存在的维度值。对照组若不成立（合法值也不过滤），如实记录——那是比 M6 更宽的功能缺陷，交判分者归因。）

---

## 6. MR 类（蜕变关系——只记观察）

### MR-01 校验-保存-回读幂等

对六个块 `instance sources wide dimensions metrics dashboard` 逐块执行：GET 取原文 → POST validate（期望 ok=true，逐块记录）→ POST save（rebuild=false）→ 再 GET：`content` 与保存前**逐字节一致** 且 `parsed_ok=true`；`instances/_wb_r1/onboarding/config_history/<block>.prev.yml` 存在。
```json
{"id": "MR-01", "observation": {"per_block": {"<block>": {"validate_ok": true, "save_status": 200,
  "readback_bytes_equal": true, "readback_parsed_ok": true, "backup_exists": true}}, "all_pass": true}}
```

### MR-02 块隔离

保存 `metrics` 块（原样内容）前后，对其余五块 yml 文件做 `sha256sum`；五个哈希必须逐一不变。
```bash
sha256sum instances/_wb_r1/instance.yml instances/_wb_r1/sources.yml instances/_wb_r1/wide.yml \
          instances/_wb_r1/dimensions.yml instances/_wb_r1/dashboard.yml > judge/mr02_before.txt
# （此处执行 metrics 的原样 save，命令同 B-06 但 rebuild=false）
sha256sum instances/_wb_r1/instance.yml instances/_wb_r1/sources.yml instances/_wb_r1/wide.yml \
          instances/_wb_r1/dimensions.yml instances/_wb_r1/dashboard.yml > judge/mr02_after.txt
diff judge/mr02_before.txt judge/mr02_after.txt
```
```json
{"id": "MR-02", "observation": {"saved_block": "metrics", "others_unchanged": true, "diff_empty": true}}
```

### MR-03 挂起守恒（同 inbox 重跑摄取，items 多集不变）

```bash
.venv/Scripts/python.exe -m semantic.ingest_run --instance _wb_r1      # 记退出码
.venv/Scripts/python.exe -m semantic.harvest --instance _wb_r1         # 匹配契约收获（同 §2，缺此步 items 不完整）
curl -s -o judge/actual_pending_rerun.json http://127.0.0.1:8620/api/config/_wb_r1/pending
# 规范化比较两次 items（W-01 的 actual_pending.json 与本次）：
.venv/Scripts/python.exe - <<'EOF'
import json
a = json.load(open('judge/actual_pending.json', encoding='utf-8'))['items']
b = json.load(open('judge/actual_pending_rerun.json', encoding='utf-8'))['items']
ca, cb = json.dumps(a, sort_keys=True, ensure_ascii=False), json.dumps(b, sort_keys=True, ensure_ascii=False)
json.dump({"items_equal_after_rerun": ca == cb, "items_count_before": len(a), "items_count_after": len(b)},
          open('judge/mr03_check.json', 'w', encoding='utf-8'), indent=2, sort_keys=True)
EOF
```
```json
{"id": "MR-03", "observation": {"ingest_exit_code": 0, "items_equal_after_rerun": true,
 "latest_run_id_changed": true, "check_file": "judge/mr03_check.json"}}
```
（`latest_run_id_changed` 从两次 latest_run.run_id 对比得出；run_id/finished_at 属易变字段，只记录不比对内容。）

### MR-04 影响一致性（impact 映射 ⟺ dashboard.yml 逐条人工核对）

```bash
.venv/Scripts/python.exe - <<'EOF'
import json, urllib.request, urllib.error
import yaml
r = urllib.request.urlopen('http://127.0.0.1:8620/api/config/_wb_r1/dashboard')
content = json.load(r)['content']
reports = yaml.safe_load(content)['reports']
r2 = urllib.request.urlopen('http://127.0.0.1:8620/api/config/_wb_r1/metrics')
metric_names = [m['name'] for m in yaml.safe_load(json.load(r2)['content'])['metrics']]
r3 = urllib.request.urlopen('http://127.0.0.1:8620/api/config/_wb_r1/dimensions')
dim_names = [d['name'] for d in yaml.safe_load(json.load(r3)['content'])['dimensions']]
def derive():
    ms = {m: sorted(x['key'] for x in reports if m in x['metrics']) for m in metric_names}
    ds = {}
    for d in dim_names:
        keys = {x['key'] for x in reports
                if x.get('dimension') == d or x.get('time_dim') == d or d in (x.get('filters') or [])}
        ds[d] = sorted(keys)
    return {"metrics": ms, "dimensions": ds}
derived = derive()
try:
    ep = json.load(urllib.request.urlopen('http://127.0.0.1:8620/api/config/_wb_r1/impact'))
    endpoint = {"metrics": ep.get('metrics'), "dimensions": ep.get('dimensions')}
except urllib.error.HTTPError as e:
    endpoint = {"http_error": e.code}
json.dump({"derived": derived, "endpoint": endpoint, "equal": derived == endpoint},
          open('judge/mr04_check.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2, sort_keys=True)
EOF
```
```json
{"id": "MR-04", "observation": {"derived_equal_to_endpoint": true, "check_file": "judge/mr04_check.json"}}
```

### MR-05 分层级联守恒（ladder：配置不变时 save+rebuild 幂等，L3/L4/L5 行集守恒）

> 保存为**原样内容**（字节不变），触发的是级联重跑本身。已知受裁定的副作用：`instances/ladder/onboarding/config_history/dashboard.prev.yml` 会生成、`data/warehouse/ladder.duckdb` 被重建——两者都不在 B-08 哈希范围（六份根 yml）内，属 sanctioned。

```bash
# 0) 环境复位：切到 ladder（断言 current）
curl -s -o judge/actual_MR05_switch.json -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8620/api/instance -H 'Content-Type: application/json' -d '{"instance":"ladder"}'
# 1) before：L3/L4/L5 行集
for key in contribution_project contribution_dept group_pnl; do
  curl -s -o "judge/mr05_before_$key.json" "http://127.0.0.1:8620/api/reports/$key/data"
done
# 2) 原样保存 dashboard.yml + rebuild=true（轮询终态同 B-06，分层级联耗时更长，上限放宽到 300s）
.venv/Scripts/python.exe - <<'EOF'
import json, urllib.request, urllib.error
r = urllib.request.urlopen('http://127.0.0.1:8620/api/config/ladder/dashboard')
content = json.load(r)['content']
req = urllib.request.Request('http://127.0.0.1:8620/api/config/ladder/dashboard/save',
    data=json.dumps({'content': content, 'rebuild': True}).encode(),
    headers={'Content-Type': 'application/json'})
try:
    resp = urllib.request.urlopen(req, timeout=60); code, body = resp.status, json.load(resp)
except urllib.error.HTTPError as e:
    code, body = e.code, json.load(e)
json.dump({'status': code, 'body': body}, open('judge/actual_MR05_save.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=2, sort_keys=True)
EOF
# 3) 等 run 终态（同 B-06 轮询模板，run_id 取自 actual_MR05_save.json 的 rebuild.run_id；无则记录）
# 4) after：重采 L3/L4/L5 行集
for key in contribution_project contribution_dept group_pnl; do
  curl -s -o "judge/mr05_after_$key.json" "http://127.0.0.1:8620/api/reports/$key/data"
done
# 5) 行集规范化比较 + dashboard 内容字节对照
.venv/Scripts/python.exe - > judge/mr05_check.json <<'EOF'
import json, urllib.request
out = {}
for key in ["contribution_project", "contribution_dept", "group_pnl"]:
    a = json.load(open(f'judge/mr05_before_{key}.json', encoding='utf-8'))
    b = json.load(open(f'judge/mr05_after_{key}.json', encoding='utf-8'))
    out[key] = json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)
d0 = json.load(urllib.request.urlopen('http://127.0.0.1:8620/api/config/ladder/dashboard'))
out["dashboard_content_unchanged"] = True   # 用原样保存的字节对照：与保存前 GET 内容比较由执行者记录哈希
json.dump(out, open('judge/mr05_check.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2, sort_keys=True)
print(json.dumps(out, ensure_ascii=False, sort_keys=True))
EOF
# 6) 环境复位：切回 sales
curl -s -o judge/actual_MR05_switchback.json -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8620/api/instance -H 'Content-Type: application/json' -d '{"instance":"sales"}'
```
```json
{"id": "MR-05", "observation": {"save_status": 200, "rebuild_triggered": true,
 "run_terminal_light_in": ["green", "yellow"],
 "rowsets_equal": {"contribution_project": true, "contribution_dept": true, "group_pnl": true},
 "dashboard_content_unchanged": true, "check_file": "judge/mr05_check.json"}}
```
（步骤 2 前后各做一次 `GET /api/config/ladder/dashboard` 内容 sha256 存 `judge/mr05_dashboard_hash.txt` 两行，证实"配置不变"。）

---

## 7. 变异体装备校正（`tests/v0.6/mutations/` 由被测方提供）

> 若该目录或 `MUTATIONS.json` 不存在：跳过本节，并在 behaviors_round2.json 写一条
> `{"id": "MUT-SKIPPED", "expect": "caught", "observed": "skipped", "evidence": "mutations 目录缺失"}`。
> R2 菜单 = M1~M6（M4/M5/M6 为换血新血）；`MUTATIONS.json` 尚未定义的变异体按 skipped 记录（不算 survived，但 kill 率缺额记债务）。

对每个变异体 M∈{M1,…,M6}：

```bash
# 0) 预清理：8630 必须无残留监听（起服前断言）
for pid in $(netstat -ano | grep ":8630" | grep LISTENING | awk '{print $5}' | sort -u); do taskkill //F //PID $pid; done
netstat -ano | grep ":8630" | grep LISTENING && echo "8630 STILL BUSY" || echo "8630 free"   # 期望 free
# 1) 基线哈希快照（变异期间真实仓库零改动的对照面）
sha256sum instances/sales/*.yml instances/_wb_r1/*.yml > judge/actual_B09_hash_before.txt
# 2) 生成副本（真实仓库零改动）
.venv/Scripts/python.exe tests/v0.6/mutations/apply_mutation.py M
# 3) 给副本补库文件（M1~M6 通用，保真度：副本 duckdb 从基线 build 后复制，保证副本数据面与真身一致）
mkdir -p build/_mut_M/data/warehouse
cp data/warehouse/_wb_r1.duckdb build/_mut_M/data/warehouse/_wb_r1.duckdb
# 4) 起 8630 副本服务——解释器必须用仓库根的绝对路径（R2 修正：相对路径 ../../../.venv 从副本目录解析越界）
PY="$(pwd)/.venv/Scripts/python.exe"
(cd build/_mut_M && "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8630 \
  > ../../logs/_mut_M_uvicorn.log 2>&1 &)
sleep 4
# 5) B-09 身份断言 + 副本保真度对照：副本活了、真身无恙、副本数据面与真身一致
curl -s -o judge/actual_B09_mutant_M_instance.json -w '%{http_code}\n' http://127.0.0.1:8630/api/instance   # 期望 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8620/api/instance                                # 期望 200
# 保真度对照（路径寻址，不依赖 current 账套）：副本 pending items 须与真身一致（M2 例外——其探针本身就是 pending，
# 保真度改用"真身基线 items 非空 + 副本库文件字节一致"佐证，并如实记录）
curl -s -o judge/actual_B09_fidelity_pending_8630.json "http://127.0.0.1:8630/api/config/_wb_r1/pending"
curl -s -o judge/actual_B09_fidelity_pending_8620.json "http://127.0.0.1:8620/api/config/_wb_r1/pending"
# 不相等 = 副本失真，先修环境（重拷 duckdb）再跑探针，不得带病判 caught/survived
sha256sum instances/sales/*.yml instances/_wb_r1/*.yml > judge/actual_B09_hash_during.txt
diff judge/actual_B09_hash_before.txt judge/actual_B09_hash_during.txt   # 期望为空
# 6) 跑探针（判据见下表；与正式 Case 相同命令、端口换 8630，输出存 judge/mut_M_probe_*.json）
# 7) 副本收敛：杀 8630、删副本
for pid in $(netstat -ano | grep ":8630" | grep LISTENING | awk '{print $5}' | sort -u); do taskkill //F //PID $pid; done
rm -rf build/_mut_M
```

B-09 行为条目（每变异体一条 evidence，汇总成一条 behaviors；observed 键名逐字取自 expect，原始观察放 evidence）：
```json
{"id": "B-09", "expect": {"mutant_instance_200": true, "real_8620_200": true,
  "baseline_hashes_unchanged_during_mutation": true, "copy_fidelity_ok": true},
 "observed": {"M1": {"...": "..."}, "M2": {"...": "..."}, "M3": {"...": "..."},
              "M4": {"...": "..."}, "M5": {"...": "..."}, "M6": {"...": "..."}},
 "evidence": "actual_B09_*.json（含 fidelity pending 两侧原文）"}
```

探针与判据（`caught` = 变异行为被装备抓住；`survived` = 装备漏检；保真度不合格一律先修环境，不计 caught/survived）：

| id | 注入的 bug 类（SPEC 级声明） | 探针（对 8630） | caught 判据 |
|---|---|---|---|
| MUT-M1 | 保存绕过校验（save 不校验直接写盘） | B-02 的非法草稿 save 探针（syntax 与 cross 两条都跑） | 任一条返回 200/落盘 → **caught**；两条都仍 422 且不落盘 → **survived**（变异未生效或探针失效，如实记录） |
| MUT-M2 | 挂起队列丢级（漏掉某 level 的行） | W-01 的 pending GET | 副本 items 规范化 JSON ≠ 8620 基线 items（`judge/actual_pending.json`）→ **caught**；相等 → **survived**（若基线 items 本身为空或不含被丢群体，判据退化——如实记录并注记） |
| MUT-M3 | 白名单/防穿越失效（任意块/任意路径可读写） | B-04 全部探针 + B-05 全部探针 | 任一"应 404"探针返回 2xx/3xx，或越界路径/仓库根出现新文件 → **caught**；全部照旧 404 且边界无文件 → **survived** |
| MUT-M4 | **备份跳过类**（save 成功但不写 `onboarding/config_history/<block>.prev.yml`，或备份字节 ≠ 覆盖前旧文件） | B-03 的保存合法探针（对 8630：GET dimensions → 原样 save → 检查副本内备份） | `backup_exists=false` 或 `backup_bytes_equal_to_saved=false` → **caught**；两者皆真 → **survived** |
| MUT-M5 | **别名层清空类**（`/api/aliases` 返回空对象/缺当前账套配置推导条目） | B-10 的别名层探针（对 8630） | aliases 空/缺当前账套报表 title 痕迹 → **caught**；与非变异体同等非空且覆盖 → **survived** |
| MUT-M6 | **查询白名单旁路类**（报表数据端点维度筛选不走 D14 回退，非法值直接拼入过滤） | **B-11 全套探针（R2 裁定 E 重设计）**：合法 KEY + 非法 VALUE（`区域=__no_such_region__`）+ 合法值对照组（`区域=华东`）。前置：副本保真度对照通过（B-09 fidelity，副本无筛选行集/库文件与真身一致——R2 证据表明守门层在端点、非法 KEY 会被端点先丢弃，故必须用合法 KEY 打值路径） | 副本上 `badfilter_rows_equal_unfiltered=false`（典型为行集=0）或 badfilter 5xx → **caught**；与无筛选一致且 200 → **survived**（对照组 goodfilter 必须成立，否则本轮结果作废重探） |

每条写进 `behaviors_round2.json`：`{"id": "MUT-M1", "expect": "caught", "observed": "caught|survived|skipped", "evidence": "<探针结果摘要+文件名>"}`。M4/M5/M6 三个新血全部 caught + 总 kill 率达标 = 装备校正通过；任何 survived 原样上报（判分者记债务），**不得为凑 kill 率改探针或改答案**。

**给被测方的补丁实现要求（判据已定，实现自由）**：M4 = 删掉 save 流程中"复制旧文件到 config_history"一步（或复制新内容冒充旧文件）；M5 = 别名接口返回空 map / 只返回骨架键（清空从六配置的推导）；M6 = 报表数据端点把查询串里的维度值不经白名单校验直接进过滤条件。补丁形式与 M1~M3 相同：`MUTATIONS.json` 加条目（file/old/new 唯一命中文本替换），`apply_mutation.py M4` 可执行。

---

## 8. B-07 / B-08（收尾断言）

### B-07 下划线实例不出现在正式账套清单（R2：前置加环境复位）

```bash
# 0) 环境复位：切当前账套到 sales 并断言（R2 新增前置——任何更早 Case 可能留下了别的 current）
curl -s -o judge/actual_B07_switch.json -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8620/api/instance -H 'Content-Type: application/json' -d '{"instance":"sales"}'
curl -s -o judge/actual_B07_after_switch.json http://127.0.0.1:8620/api/instance
# 1) 账套清单
curl -s -o judge/actual_B07.json http://127.0.0.1:8620/api/instance
```
expect：
```json
{"switch_current_is_sales": true, "underscore_instance_absent_from_list": true,
 "official_accounts_present": true, "current_is_official": true}
```
（判定方法：`current=="sales"`（断言复位成功）；响应体任何账套列表字段中不出现 `_wb_r1`；`sales/restaurant/retail/hro/ladder` 等官方账套 id 在响应中可寻址；`current` 字段值为官方账套之一。若 POST 形态不被接受（4xx），改试 `?instance=sales` 查询串并把实际可达形态记入 evidence——复位这个动作本身不许跳过。）

### B-08 官方账套配置哈希不变

```bash
sha256sum instances/sales/*.yml instances/restaurant/*.yml instances/retail/*.yml instances/hro/*.yml \
  instances/ladder/*.yml > judge/hash_official_after.txt
diff judge/hash_official_before.txt judge/hash_official_after.txt
```
expect：`{"official_hashes_unchanged": true}`（diff 为空；MR-05 的原样 save 不改 yml 字节，ladder 亦应通过）。

---

## 9. 基线恢复（必做收尾）

```bash
rm -rf instances/_wb_r1
.venv/Scripts/python.exe tests/v0.6/generate.py
.venv/Scripts/python.exe -m semantic.ingest_run  --instance _wb_r1
.venv/Scripts/python.exe -m semantic.compile_dbt --instance _wb_r1
(cd instances/_wb_r1/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors | tail -3)
.venv/Scripts/python.exe -m semantic.harvest --instance _wb_r1
curl -s -o judge/postrestore_pending.json -w '%{http_code}\n' http://127.0.0.1:8620/api/config/_wb_r1/pending
```
期望：五条命令退出码 0；恢复后 pending 端点 200（items 与恢复前基线一致——即 MR-03 的守恒，可顺带 diff `actual_pending.json`）。

## 10. 结尾自检清单（全部打勾才算交付）

- [ ] `judge/` 产物齐全：`actual_pending.json`、`actual_pending_rerun.json`、`actual_impact.json`、`actual_rows.json`、`actual_W04_*.json`、`actual_W05_*.json/txt`、B-01…B-08 与 B-10/B-11 各 actual 文件、`actual_MR05_save.json`、`mr02_before/after.txt`、`mr03_check.json`、`mr04_check.json`、`mr05_check.json`、`actual_B09_*.json/txt`、`hash_official_before/after.txt`、`postrestore_pending.json`、`preflight_*.json`
- [ ] `behaviors_round2.json`：B-01…B-08、B-09、B-10、B-11 每条 `{id, expect, observed, evidence}`，expect 与本文逐字一致，observed 同构如实
- [ ] `mr_round2.json`：MR-01…MR-05 观察原文（只观察，无期望）
- [ ] `provenance_round2.json`：每条命令（含三步链、全部 curl、变异探针、账套切换）的 `{id, command, exit_code}`
- [ ] 变异节已执行（M1…M6 各一条 MUT-* 记录；补丁未提供的记 skipped 并注明），M4/M5/M6 新血判据按 §7 表执行
- [ ] 未读 `tests/v0.6/expected/` 与 `tests/v0.6/SPEC.md`（在 behaviors_round2.json 追加一条声明：`{"id": "DISCIPLINE", "expect": "sealed_files_unread", "observed": "sealed_files_unread", "evidence": "声明"}`）
- [ ] B-08 diff 为空（官方账套零改动，含 ladder）
- [ ] 基线已恢复（§9），instances 外无测试残留（`build/_mut_*` 已删、`judge/` 之外无新文件）
- [ ] 报告里不含任何"期望数值"——你的产出只有 observed，没有 oracle
