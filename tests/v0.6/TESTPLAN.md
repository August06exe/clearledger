# TESTPLAN — v0.5 配置工作台验收（tests/v0.6，实例 `_wb_r1`）

> **你（测试 Agent）的唯一指令来源是本文。** 纪律：
> 1. **禁读** `tests/v0.6/expected/`（密封答案区）与 `tests/v0.6/SPEC.md`（场景圣经，含答案相邻信息）——读了即泄密，判分作废；
> 2. **禁改** 被测系统任何代码与官方账套（`instances/sales|restaurant|retail|hro/`）任何文件；
> 3. 你的产物**只写** `tests/v0.6/judge/`（自建目录）与临时目录 `build/_mut_*/`；
> 4. 门户已在 `http://127.0.0.1:8620` 运行——**不得重启**（变异体副本用 8630，见 §7）；
> 5. 全程工作目录 = 仓库根；Python 用 `.venv/Scripts/python.exe`；
> 6. 所有命令逐条执行并记录退出码；观测值原样入 `judge/`，**不做任何"修复"**。

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

# 1.3 官方账套配置基线哈希（B-08 的 before 快照，必须最先做）
sha256sum instances/sales/*.yml instances/restaurant/*.yml instances/retail/*.yml instances/hro/*.yml \
  > judge/hash_official_before.txt
```

## 2. 基线装配（三步链）

```bash
.venv/Scripts/python.exe tests/v0.6/generate.py                      # 幂等重建 instances/_wb_r1/
.venv/Scripts/python.exe -m semantic.ingest_run  --instance _wb_r1   # 摄取+契约校验
.venv/Scripts/python.exe -m semantic.compile_dbt --instance _wb_r1   # 配置→dbt project
(cd instances/_wb_r1/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors | tail -5)
```

- 四条命令退出码**全部记入** `judge/provenance_round1.json`（id=BASE-1..BASE-4）。
- 期望：退出码全 0；dbt build 末行 `ERROR=0`（PASS/WARN 数如实记录，不做要求）。
- 若 ingest 退出码非 0：如实记录 stderr/stderr 摘要进 provenance 并继续（这本身就是判分证据），W 类照采。

## 3. 采集规范

- 数值类 actual：`judge/actual_*.json`，保存**完整响应体**（易变字段保留在内，判分时按口径剔除）。
- 行为类断言：`judge/behaviors_round1.json`，数组，每条 `{"id": "B-xx", "expect": <本文给出的结构原样拷贝>, "observed": <同构实测>, "evidence": "<一句话+指向的 actual 文件>"}`。
- 蜕变观察：`judge/mr_round1.json`，数组，每条 `{"id": "MR-0x", "observation": {...}}`（**只记观察，不写期望**）。
- 溯源：`judge/provenance_round1.json`，数组，每条 `{"id": "<Case或步骤id>", "command": "<命令原文>", "exit_code": <int>}`。
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
- **双跑一致性自检（必做）**：随后执行 §6 的 MR-03（重跑摄取）后**再采一次** pending 存 `judge/actual_pending_rerun.json`，把两次 items 的 `json.dumps(sort_keys=true)` 规范化文本做逐字节 diff，结论（equal/not_equal）写进 `mr_round1.json` 的 MR-03 条目。

### W-02 影响预览

```bash
curl -s -o judge/actual_impact.json -w '%{http_code}\n' \
  http://127.0.0.1:8620/api/config/_wb_r1/impact
```

- actual 结构：`{"status": <http码>, "body": {"instance", "metrics": {指标: [报表key]}, "dimensions": {维度: [报表key]}}}`。
- 期望（结构性的）：200；两张映射覆盖 metrics.yml / dimensions.yml 声明的**全部**指标与维度（含未被引用者，其值必须为数组，未被引用者应为空数组——这是设计 §3.6 明文）；列表元素为报表 key 字符串。

### W-03 行数对数（raw 各源表 + 宽表）

```bash
.venv/Scripts/python.exe - > judge/actual_rows.json <<'EOF'
import json, sys, time
import duckdb
path = "data/warehouse/_wb_r1.duckdb"
con = None
for i in range(5):                       # 跑批写锁重试（只读连接）
    try:
        con = duckdb.connect(path, read_only=True); break
    except Exception as e:
        if i == 4: print(json.dumps({"error": str(e)})); sys.exit(1)
        time.sleep(2)
tables = con.execute("select table_schema, table_name from information_schema.tables").fetchall()
out = {"raw": {}, "wide_ledger": None, "schemas_seen": sorted({t[0] for t in tables})}
for schema, name in tables:
    if schema == "raw":
        n = con.execute(f'select count(*) from raw."{name}"').fetchone()[0]
        out["raw"][name] = n
    if name == "wide_ledger":
        out["wide_ledger"] = con.execute(f'select count(*) from "{schema}"."{name}"').fetchone()[0]
print(json.dumps(out, ensure_ascii=False, sort_keys=True, indent=2))
EOF
```

- actual 结构：`{"raw": {"<源表名>": 行数}, "wide_ledger": 行数|null, "schemas_seen": [...]}`（若 `wide_ledger` 为 null，如实记录并注记"宽表模型未找到"——判分证据，不是你的错误）。
- 期望（结构性的）：raw 下出现全部五个源的同名表；行数为非负整数。

---

## 5. B 类（行为断言）

> B-01…B-06 依次执行；B-07/B-08 在 MR 之后（§6）执行。每个 Case 的 `expect` 结构**原样拷贝**进 behaviors_round1.json，`observed` 同构填写实测值。

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

### B-05 路径穿越拒绝，instances 外零落盘

```bash
# 读方向（两种编码都探）
curl -s --path-as-is -o judge/actual_B05_g1.json -w '%{http_code}\n' 'http://127.0.0.1:8620/api/config/../data'
curl -s                -o judge/actual_B05_g2.json -w '%{http_code}\n' 'http://127.0.0.1:8620/api/config/%2E%2E%2Fdata'
curl -s                -o judge/actual_B05_g3.json -w '%{http_code}\n' 'http://127.0.0.1:8620/api/config/_wb_r1/%2E%2E%2F%2E%2E%2Fevil'
# 写方向（酸测：保存到越界路径）
curl -s -o judge/actual_B05_p1.json -w '%{http_code}\n' -X POST \
  'http://127.0.0.1:8620/api/config/%2E%2E%2Fdata/sources/save' -H 'Content-Type: application/json' -d '{"content":"x: 1"}'
curl -s -o judge/actual_B05_p2.json -w '%{http_code}\n' -X POST \
  'http://127.0.0.1:8620/api/config/_wb_r1/%2E%2E%2F%2E%2E%2Fevil/save' -H 'Content-Type: application/json' -d '{"content":"x: 1"}'
# 越界落盘检查（四个边界路径全部必须不存在）
for f in evil.yml data/evil.yml instances/evil.yml data/warehouse/evil.yml; do
  [ -e "$f" ] && echo "EXISTS: $f" || echo "absent: $f"
done | tee judge/actual_B05_boundary.txt
```

expect：
```json
{"g1_status_in": [400, 404], "g2_status": 404, "g3_status": 404,
 "p1_status_in": [400, 404], "p2_status_in": [400, 404],
 "boundary_files_all_absent": true}
```
（g1 若观测到 3xx 重定向，如实记录 `observed` 并在 evidence 注明——判分者归因。）

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
  grep -qE 'success|ok|green|done|fail|error|red' judge/actual_B06_poll_tail.txt && break
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
 "run_trigger": "workbench", "run_status_in": ["success", "ok", "green", "done"],
 "run_light_in": ["green", "yellow"], "metrics_content_unchanged": true}
```
（若 `/api/runs` 清单/详情无 `trigger` 字段或状态词表不同：`observed` 原样记录全部字段，`evidence` 指向 runs_list/run 两个文件——"触发器标记=workbench 且终态成功"这个行为点本身不许放弃断言。`run_status_in`/`run_light_in` 的词表覆盖 dbt 词汇与灯色词汇两套。）

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

---

## 7. 变异体装备校正（`tests/v0.6/mutations/` 由被测方提供）

> 若该目录或 `MUTATIONS.json` 不存在：跳过本节，并在 behaviors_round1.json 写一条
> `{"id": "MUT-SKIPPED", "expect": "caught", "observed": "skipped", "evidence": "mutations 目录缺失"}`。
> 本目录存在（M1/M2/M3 已定义），按 `mutations/README.md` 流程执行，要点重述如下。

对每个变异体 M∈{M1, M2, M3}：

```bash
# 1) 生成副本（真实仓库零改动）
.venv/Scripts/python.exe tests/v0.6/mutations/apply_mutation.py M
# 2) 给副本补库文件（副本只拷 app/ semantic/ instances/_wb_r1/，不含 data/）
mkdir -p build/_mut_M/data/warehouse
cp data/warehouse/_wb_r1.duckdb build/_mut_M/data/warehouse/_wb_r1.duckdb
# 3) 起 8630 副本服务
(cd build/_mut_M && ../../../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8630 \
  > ../../logs/_mut_M_uvicorn.log 2>&1 &)
sleep 4; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8630/api/instance   # 期望 200
# 4) 跑探针（与正式 Case 相同命令、端口换 8630，输出存 judge/mut_M_probe_*.json）
# 5) 副本收敛：杀 8630、删副本
for pid in $(netstat -ano | grep ":8630" | grep LISTENING | awk '{print $5}' | sort -u); do taskkill //F //PID $pid; done
rm -rf build/_mut_M
```

探针与判据（`caught` = 变异行为被装备抓住；`survived` = 装备漏检）：

| id | 注入的 bug | 探针（对 8630） | caught 判据 |
|---|---|---|---|
| MUT-M1 | 保存绕过校验 | B-02 的非法草稿 save 探针（syntax 与 cross 两条都跑） | 两条都仍返回 422 且文件不落盘 → **survived**（说明变异没生效或探针失效，如实记录）；任一条返回 200/落盘 → **caught** |
| MUT-M2 | 挂起队列丢级 | W-01 的 pending GET | 副本 items 规范化 JSON ≠ 8620 基线 items（`judge/actual_pending.json`）→ **caught**；相等 → **survived**（若 8620 基线 items 本身为空或不含被丢的级别群体，判据退化——如实记录 observed 并注记） |
| MUT-M3 | 白名单/防穿越失效 | B-04 全部探针 + B-05 全部探针 | 任一"应 404"探针返回 2xx/3xx，或越界路径出现新文件 → **caught**；全部照旧 404 且边界无文件 → **survived** |

每条写进 `behaviors_round1.json`：`{"id": "MUT-M1", "expect": "caught", "observed": "caught|survived", "evidence": "<探针结果摘要+文件名>"}`。三个全部 caught = 装备校正通过；任何 survived 原样上报（判分者记债务），**不得为凑 kill 率改探针或改答案**。

---

## 8. B-07 / B-08（收尾断言）

### B-07 下划线实例不出现在正式账套清单

```bash
curl -s -o judge/actual_B07.json http://127.0.0.1:8620/api/instance
```
expect：
```json
{"underscore_instance_absent_from_list": true, "official_accounts_present": true,
 "current_is_official": true}
```
（判定方法：响应体任何账套列表字段中不出现 `_wb_r1`；`sales/restaurant/retail/hro` 四个官方账套 id 在响应中可寻址；`current` 字段值（若有）为官方账套之一。）

### B-08 官方账套配置哈希不变

```bash
sha256sum instances/sales/*.yml instances/restaurant/*.yml instances/retail/*.yml instances/hro/*.yml \
  > judge/hash_official_after.txt
diff judge/hash_official_before.txt judge/hash_official_after.txt
```
expect：`{"official_hashes_unchanged": true}`（diff 为空）。

---

## 9. 基线恢复（必做收尾）

```bash
rm -rf instances/_wb_r1
.venv/Scripts/python.exe tests/v0.6/generate.py
.venv/Scripts/python.exe -m semantic.ingest_run  --instance _wb_r1
.venv/Scripts/python.exe -m semantic.compile_dbt --instance _wb_r1
(cd instances/_wb_r1/pipeline && ../../../.venv/Scripts/dbt.exe build --profiles-dir . --no-use-colors | tail -3)
curl -s -o judge/postrestore_pending.json -w '%{http_code}\n' http://127.0.0.1:8620/api/config/_wb_r1/pending
```
期望：四条命令退出码 0；恢复后 pending 端点 200（items 与恢复前基线一致——即 MR-03 的守恒，可顺带 diff `actual_pending.json`）。

## 10. 结尾自检清单（全部打勾才算交付）

- [ ] `judge/` 产物齐全：`actual_pending.json`、`actual_pending_rerun.json`、`actual_impact.json`、`actual_rows.json`、B-01…B-08 各 actual 文件、`mr02_before/after.txt`、`mr03_check.json`、`mr04_check.json`、`hash_official_before/after.txt`、`postrestore_pending.json`、`preflight_*.json`
- [ ] `behaviors_round1.json`：B-01…B-08 每条 `{id, expect, observed, evidence}`，expect 与本文逐字一致，observed 同构如实
- [ ] `mr_round1.json`：MR-01…MR-04 观察原文（只观察，无期望）
- [ ] `provenance_round1.json`：每条命令（含三步链、全部 curl、变异探针）的 `{id, command, exit_code}`
- [ ] 变异节已执行（或已写 MUT-SKIPPED），MUT-* 三条齐
- [ ] 未读 `tests/v0.6/expected/` 与 `tests/v0.6/SPEC.md`（在 behaviors_round1.json 追加一条声明：`{"id": "DISCIPLINE", "expect": "sealed_files_unread", "observed": "sealed_files_unread", "evidence": "声明"}`）
- [ ] B-08 diff 为空（官方账套零改动）
- [ ] 基线已恢复（§9），instances 外无测试残留（`build/_mut_*` 已删、`judge/` 之外无新文件）
- [ ] 报告里不含任何"期望数值"——你的产出只有 observed，没有 oracle
