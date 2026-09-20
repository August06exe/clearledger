#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""明账 ClearLedger tests/v0.6 机械判分器（评审专用）——数字对错由本脚本裁定，LLM 永不裁数字。

用法（工作目录 = 仓库根）：
  .venv/Scripts/python.exe tests/v0.6/judge/score.py --tag round1 \
      [--actual-dir tests/v0.6/judge] [--expected-dir tests/v0.6/expected] [--strict-manifest]

CLI：
  --tag roundN        产物名 score_<tag>.json（禁固定名覆盖）；tag 限 [A-Za-z0-9_-]
  --actual-dir        测试 Agent 产物目录（actual_*.json / behaviors_<tag>.json /
                      mr_<tag>.json / mr02_before|after.txt / mr04_check.json 等），
                      默认 = 本脚本所在目录（judge/）
  --expected-dir      密封区（answer.json / caliber.json / manifest.sha256 / oracle.py），
                      默认 = <脚本目录>/../expected
  --strict-manifest   校验 expected/manifest.sha256：逐条 sha256 全对才继续判分；
                      任一不符 → 中止判分（产物记 aborted，全部 case NOT_RUN）。
                      结果记 manifest_verified（true/false；未加本参数 = null 未校验）

case 注册表（= TESTPLAN Case 全集，固定 19 条；增删 = 口径变更 = 密封区重封后改本表）：
  W   W-01 pending 稳定投影 / W-02 impact 两映射 / W-03 行数对数
  B   B-01..B-08 行为断言（behaviors_<tag>.json）
  MR  MR-01..MR-04 蜕变关系（mr_<tag>.json）
  MUT MUT-M1..M3 变异体装备校正（behaviors_<tag>.json 内 id=MUT-* 条目）
  特殊 DISCIPLINE 纪律声明（behaviors_<tag>.json 内）

判分口径（依据 expected/caliber.json 声明）：
  W-01 pending.items = set_of_tuples：投影 (source,field,rule,level,cnt) 多重集无序比对
       （cnt 整数精确、其余文本精确）；aux：actual 每个 item 的 sample 须非空字符串
       （nonempty_text，内容不比）；item 恰有六字段（TESTPLAN §4 结构性期望）；
       易变字段（latest_run.*、note）不比；actual 顶层 instance 须与密封一致
  W-02 impact = json_exact：metrics/dimensions 两映射 sort_keys 规范化后精确
       （列表保序——设计 §3.6 声明报表 key 升序，键序无关但列表序参与判定）
  W-03 rows = int_exact：answer.rows.files.<源> ↔ actual.raw.<源>；
       answer.rows.raw."raw.<源>" ↔ actual.raw.<源>（镜像语义 A5）；
       rows.wide_ledger 精确（null/缺失 = 失败）；actual 多出的未声明 raw 表
       只记 info 不判失败（answer 只声明五源镜像，contract_report 等系统表属引擎自留）
  B   逐条 {id, expect, observed, evidence}：expect = TESTPLAN 结构原样、observed 同构实测。
       逐字段机械比对：标量 → 类型感知精确相等（bool != int，"200" != 200）；
       键名以 _in 结尾且期望为列表 → observed 值须属于该词表（成员判定）；
       其余列表/对象 → sort_keys 规范化精确；observed 键集须与 expect 完全一致。
       evidence 缺失/空 → INVALID（缺证据即失败）；结构残缺 → INVALID（计失败）
  MR  逐条 {id, observation}（只记观察），按声明关系机械判定 holds/broken：
       MR-01 校验-保存-回读幂等：六块（instance/sources/wide/dimensions/metrics/dashboard）
             每块五条件全真（validate_ok / save_status==200 / readback_bytes_equal /
             readback_parsed_ok / backup_exists），且 observation.all_pass 与复算一致
       MR-02 块隔离：saved_block==metrics、others_unchanged/diff_empty 为真，
             且以 mr02_before.txt vs mr02_after.txt 复算（排序行集相等 = 哈希不变）
       MR-03 挂起守恒：ingest_exit_code==0、latest_run_id_changed 为真，且以
             actual_pending.json vs actual_pending_rerun.json 复算五元组多重集相等
             （复算为权威；复算相等而 claim=false 时仍 holds 并注记）
       MR-04 影响一致：claimed flag 为真，且以 mr04_check.json 复算 derived==endpoint
             （映射规范化相等）
  MUT expect 必须 "caught"；observed=caught → PASS；survived/skipped/其他 → FAIL
       并计入变异债务（mutations.debt）；kill 率 = caught/(caught+survived)
  DISCIPLINE expect 必须 "sealed_files_unread" 且与 observed 精确相等

结果分档：PASS / FAIL / NOT_RUN（缺输入文件，如缺 actual）/ INVALID（残缺 JSON、
结构不符、缺 evidence、未注册 id——一律计入 failed，不静默洗绿）。
grand = {total, passed, failed, not_run, all_green}；all_green = 零失败零未跑且 total>0。

产物 score_<tag>.json：manifest 校验明细与 manifest_verified、密封区哈希回显
（answer/caliber/oracle/manifest 自身）、score.py 自身 sha256、caliber 容差类回显、
逐 case 明细与失败清单、变异债务与 kill 统计、grand、generated_at。
除 generated_at 外同输入逐字节同输出。退出码恒为 0（结果看 JSON；argparse 用法错误除外）。
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# ---- case 注册表（冻结：增删条目 = 口径变更） ----
W_CASES = ("W-01", "W-02", "W-03")
B_CASES = tuple("B-%02d" % i for i in range(1, 9))
MR_CASES = tuple("MR-%02d" % i for i in range(1, 5))
MUT_CASES = ("MUT-M1", "MUT-M2", "MUT-M3")
SPECIAL_CASES = ("DISCIPLINE",)
ALL_CASES = list(W_CASES + B_CASES + MR_CASES + MUT_CASES + SPECIAL_CASES)


def kind_of(cid: str) -> str:
    if cid in W_CASES:
        return "W"
    if cid in B_CASES:
        return "B"
    if cid in MR_CASES:
        return "MR"
    if cid in MUT_CASES or cid.startswith("MUT"):
        return "MUT"
    if cid in SPECIAL_CASES:
        return "DISCIPLINE"
    return "UNKNOWN"

W_INPUTS = {"W-01": "actual_pending.json", "W-02": "actual_impact.json",
            "W-03": "actual_rows.json"}

PENDING_TUPLE_FIELDS = ("source", "field", "rule", "level", "cnt")
PENDING_ITEM_FIELDS = frozenset(PENDING_TUPLE_FIELDS) | {"sample"}
MR01_BLOCKS = ("dashboard", "dimensions", "instance", "metrics", "sources", "wide")
TAG_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ---------------------------------------------------------------- 基础工具
def canon(v) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def unwrap(data):
    """actual 文件容错：若为 {status, body} 包装则取 body，否则视为 body 本身
    （TESTPLAN 的 curl -o 落盘的是裸响应体，status 只进 stdout/provenance）。"""
    if isinstance(data, dict) and "body" in data and "status" in data:
        return data["body"]
    return data


def load_json_file(p: Path):
    """返回 (data, error)；error="missing" 表示文件不存在，其余为读取/解析错误文本。"""
    if not p.exists():
        return None, "missing"
    try:
        return json.loads(p.read_text(encoding="utf-8-sig")), None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return None, f"{type(e).__name__}: {e}"


def new_case(cid: str, kind: str) -> dict:
    return {"id": cid, "kind": kind, "result": "NOT_RUN", "failures": [], "info": {}}


# ---------------------------------------------------------------- 密封区 / manifest
def verify_manifest(exp_dir: Path):
    """逐条校验 manifest.sha256。返回 (verified: bool|None, own_sha, entries)。"""
    mp = exp_dir / "manifest.sha256"
    if not mp.exists():
        return None, None, [{"name": "manifest.sha256", "ok": False, "error": "文件缺失"}]
    own = sha256_file(mp)
    entries = []
    try:
        lines = [ln.strip() for ln in mp.read_text(encoding="utf-8-sig").splitlines()
                 if ln.strip()]
    except (OSError, UnicodeDecodeError) as e:
        return False, own, [{"name": "manifest.sha256", "ok": False, "error": str(e)}]
    for ln in lines:
        parts = ln.split(None, 1)
        if len(parts) != 2:
            entries.append({"name": ln[:64], "ok": False, "error": "行格式非法（应为 '<sha256>  <文件名>'）"})
            continue
        want, name = parts[0].lower(), parts[1].strip()
        f = exp_dir / name
        if not f.exists():
            entries.append({"name": name, "expected": want, "ok": False, "error": "文件缺失"})
            continue
        got = sha256_file(f)
        entries.append({"name": name, "expected": want, "actual": got, "ok": got == want})
    verified = bool(entries) and all(e.get("ok") for e in entries)
    return verified, own, entries


# ---------------------------------------------------------------- W 路
def pending_tuples_of(body):
    """从 pending body 提取五元组列表；结构不符返回 None。"""
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return None
    out = []
    for it in items:
        if not isinstance(it, dict):
            return None
        try:
            out.append((it["source"], it["field"], it["rule"], it["level"], it["cnt"]))
        except KeyError:
            return None
    return out


def judge_w01(answer: dict, data) -> tuple:
    """挂起队列稳定投影。返回 (failures, info)。"""
    fails, info = [], {}
    body = unwrap(data)
    if not isinstance(body, dict):
        return [{"type": "invalid_structure", "detail": "顶层不是对象"}], info
    if isinstance(data, dict) and is_int(data.get("status")) and data["status"] != 200:
        fails.append({"type": "status_not_200", "expected": 200, "actual": data["status"]})
    if body.get("instance") != answer.get("instance"):
        fails.append({"type": "instance_mismatch", "expected": answer.get("instance"),
                      "actual": body.get("instance")})
    items = body.get("items")
    if not isinstance(items, list):
        fails.append({"type": "invalid_structure", "detail": "items 不是数组"})
        return fails, info
    info["actual_items"] = len(items)
    ans_items = (answer.get("pending") or {}).get("items") or []
    info["answer_items"] = len(ans_items)

    # 结构性检查（TESTPLAN §4：恰有六字段；cnt 非负整数；sample 非空字符串）
    tuples_act = []
    for i, it in enumerate(items):
        ident = {"index": i}
        if not isinstance(it, dict):
            fails.append({"type": "item_not_object", **ident})
            continue
        keys = set(it)
        miss, extra = PENDING_ITEM_FIELDS - keys, keys - PENDING_ITEM_FIELDS
        if miss:
            fails.append({"type": "item_missing_fields", "fields": sorted(miss), **ident})
        if extra:
            fails.append({"type": "item_extra_fields", "fields": sorted(extra), **ident})
        for f in ("source", "field", "rule", "level"):
            if not isinstance(it.get(f), str):
                fails.append({"type": "item_field_type", "field": f,
                              "expected": "string", "actual": it.get(f), **ident})
        cnt = it.get("cnt")
        if not is_int(cnt) or cnt < 0:
            fails.append({"type": "item_cnt_type", "field": "cnt",
                          "expected": "非负整数", "actual": cnt, **ident})
        sample = it.get("sample")
        if not (isinstance(sample, str) and len(sample) > 0):
            fails.append({"type": "sample_not_nonempty", "field": "sample",
                          "rule": "nonempty_text（设计 §3.5）", "actual": sample, **ident})
        if not (miss or extra):
            try:
                tuples_act.append(tuple(it[f] for f in PENDING_TUPLE_FIELDS))
            except KeyError:
                pass
    tuples_ans = [(t.get("source"), t.get("field"), t.get("rule"), t.get("level"),
                   int(t["cnt"])) for t in ans_items]
    ca, cb = Counter(tuples_ans), Counter(tuples_act)
    if ca != cb:
        missing = ca - cb   # 答案有、actual 无
        extra = cb - ca     # actual 有、答案无
        fmt = lambda c: [{"source": s, "field": f, "rule": r, "level": lv, "cnt": n,
                          "count": c} for (s, f, r, lv, n), c in sorted(c.items())]
        fails.append({"type": "items_set_mismatch",
                      "detail": "set_of_tuples 多重集无序比对 (source,field,rule,level,cnt)",
                      "missing_in_actual": fmt(missing), "unexpected_in_actual": fmt(extra)})
    return fails, info


def judge_w02(answer: dict, data) -> tuple:
    """影响预览：json_exact 两映射。"""
    fails, info = [], {}
    body = unwrap(data)
    if not isinstance(body, dict):
        return [{"type": "invalid_structure", "detail": "顶层不是对象"}], info
    if isinstance(data, dict) and is_int(data.get("status")) and data["status"] != 200:
        fails.append({"type": "status_not_200", "expected": 200, "actual": data["status"]})
    if body.get("instance") != answer.get("instance"):
        fails.append({"type": "instance_mismatch", "expected": answer.get("instance"),
                      "actual": body.get("instance")})
    exp_imp = answer.get("impact") or {}
    for part in ("metrics", "dimensions"):
        exp, act = exp_imp.get(part), body.get(part)
        if canon(exp) != canon(act):
            fails.append({"type": "impact_mismatch", "part": part, "class": "json_exact",
                          "detail": "sort_keys 规范化后不相等（对象键序无关，列表保序）",
                          "expected": exp, "actual": act})
    return fails, info


def judge_w03(answer: dict, data) -> tuple:
    """行数对数：int_exact。"""
    fails, info = [], {}
    body = unwrap(data)
    if not isinstance(body, dict):
        return [{"type": "invalid_structure", "detail": "顶层不是对象"}], info
    raw = body.get("raw")
    if not isinstance(raw, dict):
        fails.append({"type": "invalid_structure", "detail": "raw 不是对象"})
        raw = {}

    def check(key: str, expect_n, src_table: str):
        act = raw.get(src_table)
        if not is_int(act):
            fails.append({"type": "rows_mismatch", "key": key, "class": "int_exact",
                          "expected": expect_n, "actual": act,
                          "detail": "raw 表缺失或行数非整数" if act is None else "行数非整数"})
        elif act != expect_n:
            fails.append({"type": "rows_mismatch", "key": key, "class": "int_exact",
                          "expected": expect_n, "actual": act})

    rows_ans = answer.get("rows") or {}
    for src, n in sorted((rows_ans.get("files") or {}).items()):
        check(f"files.{src}", n, src)
    raw_keys = rows_ans.get("raw") or {}
    for key, n in sorted(raw_keys.items()):
        if isinstance(key, str) and key.startswith("raw."):
            check(key, n, key[len("raw."):])
        else:
            fails.append({"type": "invalid_structure", "detail": f"answer.rows.raw 键非法: {key!r}"})
    exp_wide = rows_ans.get("wide_ledger")
    act_wide = body.get("wide_ledger")
    if not is_int(act_wide) or act_wide != exp_wide:
        fails.append({"type": "rows_mismatch", "key": "wide_ledger", "class": "int_exact",
                      "expected": exp_wide, "actual": act_wide,
                      "detail": "宽表为 null/缺失——如实判失败（判分证据，非采集错误）"})
    declared = set(rows_ans.get("files") or {}) | {k[len("raw."):] for k in raw_keys
                                                   if isinstance(k, str) and k.startswith("raw.")}
    extra_tables = sorted(t for t in raw if t not in declared)
    if extra_tables:
        info["extra_raw_tables_not_judged"] = extra_tables
    return fails, info


# ---------------------------------------------------------------- B 路
def cmp_field(key: str, exp, act):
    """返回 None=通过，否则失败原因串。_in 结尾且期望为列表 → 成员判定。"""
    if key.endswith("_in") and isinstance(exp, list):
        return None if act in exp else "not_in_vocabulary"
    if isinstance(exp, bool) or isinstance(act, bool):
        ok = isinstance(exp, bool) and isinstance(act, bool) and exp is act
        return None if ok else "type_or_value_mismatch"
    if isinstance(exp, (int, float)) and isinstance(act, (int, float)):
        return None if exp == act else "value_mismatch"
    if exp is None or act is None:
        return None if (exp is None and act is None) else "null_mismatch"
    if isinstance(exp, str) and isinstance(act, str):
        return None if exp == act else "value_mismatch"
    return None if canon(exp) == canon(act) else "value_mismatch"


def judge_behavior_entry(cid: str, e: dict):
    """返回 (failures, info, invalid)。invalid=True → 结果 INVALID（结构残缺）。"""
    fails, info = [], {}
    expect, observed = e.get("expect"), e.get("observed")
    ev = e.get("evidence")
    info.update({"expect": expect, "observed": observed, "evidence": ev})
    invalid = False
    if not (isinstance(ev, str) and ev.strip()):
        fails.append({"type": "evidence_missing",
                      "detail": "evidence 缺失或空（缺证据即失败）"})
        invalid = True
    if cid == "DISCIPLINE":
        if expect != "sealed_files_unread":
            fails.append({"type": "expect_not_declared_literal",
                          "expected": "sealed_files_unread", "actual": expect})
            invalid = True
        elif observed != expect:
            fails.append({"type": "discipline_violation",
                          "expect": expect, "observed": observed})
        return fails, info, invalid
    if cid.startswith("MUT"):
        if expect != "caught":
            fails.append({"type": "expect_not_caught",
                          "expected": "caught", "actual": expect})
            return fails, info, True
        if not isinstance(observed, str):
            fails.append({"type": "observed_not_enum", "observed": observed})
            return fails, info, True
        if observed != "caught":
            fails.append({"type": "mutation_survived", "observed": observed})
        return fails, info, invalid
    # B-*：结构对象逐字段比对
    if not isinstance(expect, dict) or not isinstance(observed, dict):
        fails.append({"type": "expect_observed_not_object",
                      "expect_type": type(expect).__name__,
                      "observed_type": type(observed).__name__,
                      "detail": "B 类 expect 须为 TESTPLAN 结构对象、observed 同构"})
        return fails, info, True
    ks_e, ks_o = set(expect), set(observed)
    if ks_e != ks_o:
        fails.append({"type": "observed_schema_mismatch",
                      "missing_fields": sorted(ks_e - ks_o),
                      "extra_fields": sorted(ks_o - ks_e),
                      "detail": "observed 须与 expect 同构（键集完全一致）"})
        return fails, info, True
    for k in sorted(ks_e):
        why = cmp_field(k, expect[k], observed[k])
        if why:
            fails.append({"type": "field_mismatch", "field": k,
                          "expected": expect[k], "observed": observed[k], "why": why})
    return fails, info, invalid


# ---------------------------------------------------------------- MR 路
def judge_mr_entry(cid: str, e: dict, actual_dir: Path):
    """返回 (failures, info, invalid)。"""
    fails, info = [], {}
    obs = e.get("observation")
    if not isinstance(obs, dict):
        return [{"type": "observation_missing_or_not_object"}], info, True

    if cid == "MR-01":
        per = obs.get("per_block")
        if not isinstance(per, dict):
            return [{"type": "per_block_missing_or_not_object"}], info, True
        blocks = sorted(set(MR01_BLOCKS) | set(k for k in per if isinstance(k, str)))
        for b in blocks:
            blk = per.get(b)
            if not isinstance(blk, dict):
                fails.append({"type": "mr01_block_missing", "block": b})
                continue
            if blk.get("validate_ok") is not True:
                fails.append({"type": "mr01_block_field", "block": b, "field": "validate_ok",
                              "expected": True, "observed": blk.get("validate_ok")})
            ss = blk.get("save_status")
            if not (is_int(ss) and ss == 200):
                fails.append({"type": "mr01_block_field", "block": b, "field": "save_status",
                              "expected": 200, "observed": ss})
            for fname in ("readback_bytes_equal", "readback_parsed_ok", "backup_exists"):
                if blk.get(fname) is not True:
                    fails.append({"type": "mr01_block_field", "block": b, "field": fname,
                                  "expected": True, "observed": blk.get(fname)})
        computed = not any(str(f.get("type", "")).startswith("mr01") for f in fails)
        ap = obs.get("all_pass")
        if not isinstance(ap, bool):
            fails.append({"type": "all_pass_not_bool", "observed": ap})
            return fails, info, True
        if ap != computed:
            fails.append({"type": "all_pass_inconsistent",
                          "claimed": ap, "recomputed": computed})
        return fails, info, False

    if cid == "MR-02":
        sb = obs.get("saved_block")
        if sb != "metrics":
            fails.append({"type": "mr02_wrong_saved_block",
                          "expected": "metrics", "observed": sb})
        for flag in ("others_unchanged", "diff_empty"):
            v = obs.get(flag)
            if not isinstance(v, bool):
                fails.append({"type": "mr02_flag_not_bool", "flag": flag, "observed": v})
                return fails, info, True
            if v is False:
                fails.append({"type": "mr02_flag_false", "flag": flag})
        bfp, afp = actual_dir / "mr02_before.txt", actual_dir / "mr02_after.txt"
        if not (bfp.exists() and afp.exists()):
            fails.append({"type": "evidence_file_missing",
                          "files": [str(bfp.name), str(afp.name)],
                          "detail": "哈希快照缺失，块隔离无法独立复算（缺证据即失败）"})
            return fails, info, False
        lb = sorted(ln for ln in bfp.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                    if ln.strip())
        la = sorted(ln for ln in afp.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                    if ln.strip())
        info["recomputed_hash_sets_equal"] = lb == la
        if lb != la:
            fails.append({"type": "mr02_hash_changed_on_recompute",
                          "detail": "mr02_before/after.txt 复算：其余五块哈希发生变化"})
        return fails, info, False

    if cid == "MR-03":
        code = obs.get("ingest_exit_code")
        if not is_int(code):
            fails.append({"type": "ingest_exit_code_not_int", "observed": code})
            return fails, info, True
        if code != 0:
            fails.append({"type": "mr03_ingest_failed", "exit_code": code})
        chg = obs.get("latest_run_id_changed")
        if not isinstance(chg, bool):
            fails.append({"type": "flag_not_bool", "flag": "latest_run_id_changed",
                          "observed": chg})
            return fails, info, True
        if chg is False:
            fails.append({"type": "mr03_rerun_did_not_happen",
                          "detail": "latest_run.run_id 未变化——守恒失去前提"})
        claim = obs.get("items_equal_after_rerun")
        if not isinstance(claim, bool):
            fails.append({"type": "flag_not_bool", "flag": "items_equal_after_rerun",
                          "observed": claim})
            return fails, info, True
        pa, pb = actual_dir / "actual_pending.json", actual_dir / "actual_pending_rerun.json"
        if not (pa.exists() and pb.exists()):
            fails.append({"type": "evidence_file_missing",
                          "files": [pa.name, pb.name],
                          "detail": "两次 pending 采集缺失，守恒无法独立复算（缺证据即失败）"})
            return fails, info, False
        da, ea = load_json_file(pa)
        db_, eb = load_json_file(pb)
        if ea or eb:
            fails.append({"type": "evidence_file_unreadable", "error": ea or eb})
            return fails, info, False
        ta, tb = pending_tuples_of(unwrap(da)), pending_tuples_of(unwrap(db_))
        if ta is None or tb is None:
            fails.append({"type": "evidence_structure_invalid",
                          "detail": "pending 证据文件 items 结构不符，无法投影五元组"})
            return fails, info, False
        eq = Counter(ta) == Counter(tb)
        info["recomputed_items_equal"] = eq
        info["items_count_before"], info["items_count_after"] = len(ta), len(tb)
        if not eq:
            fails.append({"type": "mr03_items_not_conserved",
                          "detail": "(source,field,rule,level,cnt) 多重集在重跑后不相等"})
        elif claim is False:
            info["note"] = "claim=items_equal_after_rerun=false 但复算相等：以复算为准，守恒 holds"
        return fails, info, False

    if cid == "MR-04":
        flag = obs.get("derived_equal_to_endpoint")
        if not isinstance(flag, bool):
            fails.append({"type": "flag_not_bool", "flag": "derived_equal_to_endpoint",
                          "observed": flag})
            return fails, info, True
        if flag is False:
            fails.append({"type": "mr04_flag_false"})
        cf = actual_dir / "mr04_check.json"
        if not cf.exists():
            fails.append({"type": "evidence_file_missing", "files": [cf.name],
                          "detail": "复算依据缺失（缺证据即失败）"})
            return fails, info, False
        data, err = load_json_file(cf)
        if err:
            fails.append({"type": "evidence_file_unreadable", "error": err})
            return fails, info, False
        d, p = data.get("derived"), data.get("endpoint")
        if not isinstance(d, dict) or not isinstance(p, dict):
            fails.append({"type": "evidence_structure_invalid",
                          "detail": "mr04_check.json 缺 derived/endpoint 对象"})
            return fails, info, False
        eq = canon(d) == canon(p)
        info["recomputed_equal"] = eq
        if not eq:
            fails.append({"type": "mr04_recomputed_mismatch",
                          "detail": "derived 与 endpoint 规范化后不相等（映射须逐键一致）"})
        return fails, info, False

    return [{"type": "mr_rule_not_implemented", "detail": f"未注册的蜕变关系: {cid}"}], info, True


# ---------------------------------------------------------------- 产物与摘要
def write_score(out_path: Path, result: dict):
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def print_summary(result: dict, out_path: Path):
    tag = result["tag"]
    mv = result.get("manifest_verified")
    print("== 明账 ClearLedger v0.6 机械判分器 ==")
    print(f"tag={tag}  actual_dir={result['inputs']['actual_dir']}  "
          f"strict_manifest={result.get('strict_manifest')}")
    print(f"manifest_verified={mv}")
    sealed = result.get("sealed") or {}
    print(f"sealed: answer={sealed.get('answer_sha256', '-')[:16]}…  "
          f"caliber={sealed.get('caliber_sha256', '-')[:16]}…  "
          f"manifest={sealed.get('manifest_sha256', '-')[:16]}…")
    print(f"score.py sha256={result.get('score_py_sha256', '-')[:16]}…")
    if result.get("aborted"):
        print(f"[中止] {result['aborted']}")
    print("-" * 78)
    print(f"{'Case':<16}{'Kind':<12}{'Result':<9}失败  摘要")
    for c in result.get("cases", []):
        brief = "; ".join(str(f.get("type")) for f in c["failures"][:4])
        if len(c["failures"]) > 4:
            brief += f" …(共{len(c['failures'])}条)"
        note = c.get("info", {}).get("not_run_reason", "")
        line = f"{c['id']:<16}{c['kind']:<12}{c['result']:<9}" \
               f"{len(c['failures']) if c['result'] != 'NOT_RUN' else '-':<4} "
        line += brief or note
        print(line)
    print("-" * 78)
    g = result.get("grand") or {}
    print(f"grand: total={g.get('total')}  passed={g.get('passed')}  failed={g.get('failed')}  "
          f"not_run={g.get('not_run')}  all_green={g.get('all_green')}")
    m = result.get("mutations") or {}
    kr = m.get("kill_rate")
    print(f"mutations: caught={m.get('caught')}  survived={m.get('survived')}  "
          f"skipped={m.get('skipped')}  kill_rate={kr if kr is not None else 'N/A'}  "
          f"debt={len(m.get('debt') or [])}")
    print(f"产物: {out_path}")


def build_grand(cases):
    passed = sum(1 for c in cases if c["result"] == "PASS")
    failed = sum(1 for c in cases if c["result"] in ("FAIL", "INVALID"))
    not_run = sum(1 for c in cases if c["result"] == "NOT_RUN")
    total = len(cases)
    return {"total": total, "passed": passed, "failed": failed, "not_run": not_run,
            "all_green": total > 0 and failed == 0 and not_run == 0}


def mutation_stats(cases):
    caught = survived = skipped = 0
    debt = []
    for c in cases:
        if c["kind"] != "MUT":
            continue
        obs = (c.get("info") or {}).get("observed")
        if obs == "caught":
            caught += 1
        elif obs == "survived":
            survived += 1
        elif obs == "skipped":
            skipped += 1
        if c["result"] in ("FAIL", "INVALID"):
            debt.append({"id": c["id"], "observed": obs,
                         "reason": [f.get("type") for f in c["failures"]],
                         "evidence": (c.get("info") or {}).get("evidence")})
    n = caught + survived
    return {"caught": caught, "survived": survived, "skipped": skipped,
            "kill_rate": (caught / n) if n else None, "debt": debt}


def fatal(result: dict, out_path: Path, message: str) -> int:
    result["aborted"] = message
    for c in result.get("cases", []):
        c["result"] = "NOT_RUN"
        c["info"]["not_run_reason"] = f"判分中止：{message}"
    result["grand"] = build_grand(result["cases"])
    result["failures"] = []
    write_score(out_path, result)
    print_summary(result, out_path)
    return 0


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(
        description="明账 ClearLedger tests/v0.6 机械判分器（退出码恒 0，结果看 JSON）")
    ap.add_argument("--tag", required=True, help="轮次标签，如 round1 / selftest")
    ap.add_argument("--actual-dir", default=str(SCRIPT_DIR),
                    help="测试产物目录（默认：本脚本所在 judge/）")
    ap.add_argument("--expected-dir", default=str(SCRIPT_DIR.parent / "expected"),
                    help="密封区目录（默认：<脚本目录>/../expected）")
    ap.add_argument("--strict-manifest", action="store_true",
                    help="校验 manifest.sha256，全对才继续判分")
    args = ap.parse_args()

    tag = args.tag
    actual_dir = Path(args.actual_dir)
    exp_dir = Path(args.expected_dir)
    out_path = actual_dir / f"score_{tag}.json"

    base = {
        "suite": "tests/v0.6",
        "tag": tag,
        "strict_manifest": bool(args.strict_manifest),
        "manifest_verified": None,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "score_py_sha256": sha256_file(Path(__file__)),
    }
    if not TAG_RE.match(tag):
        print(f"[失败] --tag 只允许 [A-Za-z0-9_-]: {tag!r}", file=sys.stderr)
        return 0

    # --- 密封区装载（缺件/坏 JSON = 判分环境错误，产物记 aborted，恒退出 0） ---
    answer, e1 = load_json_file(exp_dir / "answer.json")
    caliber, e2 = load_json_file(exp_dir / "caliber.json")
    verified, manifest_own, manifest_entries = verify_manifest(exp_dir)
    base["manifest_verified"] = verified if args.strict_manifest else None
    sealed = {
        "answer_sha256": sha256_file(exp_dir / "answer.json") if (exp_dir / "answer.json").exists() else None,
        "caliber_sha256": sha256_file(exp_dir / "caliber.json") if (exp_dir / "caliber.json").exists() else None,
        "oracle_sha256": sha256_file(exp_dir / "oracle.py") if (exp_dir / "oracle.py").exists() else None,
        "manifest_sha256": manifest_own,
    }
    base["sealed"] = sealed
    base["manifest_entries"] = manifest_entries
    base["inputs"] = {"actual_dir": str(actual_dir), "expected_dir": str(exp_dir)}

    def aborted_result(message):
        result = dict(base)
        result["cases"] = [dict(new_case(cid, kind_of(cid))) for cid in ALL_CASES]
        result["mutations"] = {"caught": 0, "survived": 0, "skipped": 0,
                               "kill_rate": None, "debt": []}
        return fatal(result, out_path, message)

    if e1 or e2 or answer is None or caliber is None:
        return aborted_result(
            f"密封区不可用：answer={e1} caliber={e2}（缺件或坏 JSON，不判分）")

    if args.strict_manifest and not verified:
        bad = [e for e in manifest_entries if not e.get("ok")]
        return aborted_result(
            f"--strict-manifest：manifest.sha256 校验未全对（{len(bad)} 条不符），"
            f"密封区可疑，拒绝判分")

    # --- case 注册表 ---
    cases = {cid: new_case(cid, kind_of(cid)) for cid in ALL_CASES}
    adhoc = []

    # --- W 路 ---
    for cid, fname in W_INPUTS.items():
        case = cases[cid]
        p = actual_dir / fname
        if not p.exists():
            case["info"]["not_run_reason"] = f"{fname} 缺失"
            continue
        data, err = load_json_file(p)
        if err:
            case["result"] = "INVALID"
            case["failures"].append({"type": "actual_file_unreadable", "file": fname, "error": err})
            continue
        try:
            if cid == "W-01":
                fails, info = judge_w01(answer, data)
            elif cid == "W-02":
                fails, info = judge_w02(answer, data)
            else:
                fails, info = judge_w03(answer, data)
            case["failures"], case["info"] = fails, {**case["info"], **info}
            case["result"] = None  # 交由汇总阶段按 failures 定 PASS/FAIL
        except Exception as e:  # 判分器自身意外 = 该 case invalid，不崩全程
            case["result"] = "INVALID"
            case["failures"].append({"type": "judge_exception", "error": repr(e)})

    # --- B / MUT / DISCIPLINE 路 ---
    bpath = actual_dir / f"behaviors_{tag}.json"
    base["inputs"]["behaviors_file"] = str(bpath) if bpath.exists() else None
    raw, err = load_json_file(bpath)
    if err == "missing":
        for cid in B_CASES + MUT_CASES + SPECIAL_CASES:
            cases[cid]["info"]["not_run_reason"] = f"{bpath.name} 缺失"
        raw = None
    elif err or not isinstance(raw, list):
        for cid in B_CASES + MUT_CASES + SPECIAL_CASES:
            c = cases[cid]
            c["result"] = "INVALID"
            c["failures"].append({"type": "behaviors_file_unreadable",
                                  "file": bpath.name, "error": err or "顶层不是数组"})
        raw = None

    if raw is not None:
        by_id, dups, no_id = {}, {}, []
        for i, e in enumerate(raw):
            if not isinstance(e, dict) or not isinstance(e.get("id"), str):
                no_id.append(i)
                continue
            cid = e["id"]
            if cid in by_id:
                dups.setdefault(cid, []).append(i)
            else:
                by_id[cid] = e
        for i in no_id:
            c = new_case(f"BEHAVIORS-ENTRY-{i}", "B")
            c["result"] = "INVALID"
            c["failures"].append({"type": "entry_missing_or_bad_id"})
            adhoc.append(c)
        registry = set(B_CASES + MUT_CASES + SPECIAL_CASES)
        for cid, e in by_id.items():
            if cid in cases:
                case = cases[cid]
                if cid in dups:
                    case["result"] = "INVALID"
                    case["failures"].append({"type": "duplicate_entry",
                                             "dup_indexes": dups[cid]})
                    continue
                try:
                    fails, info, invalid = judge_behavior_entry(cid, e)
                    case["failures"], case["info"] = fails, {**case["info"], **info}
                    case["result"] = "INVALID" if invalid else None
                except Exception as ex:
                    case["result"] = "INVALID"
                    case["failures"].append({"type": "judge_exception", "error": repr(ex)})
            elif cid == "MUT-SKIPPED":  # TESTPLAN §7 认可的跳过声明
                c = new_case(cid, "MUT")
                try:
                    fails, info, invalid = judge_behavior_entry(cid, e)
                    c["failures"], c["info"] = fails, info
                    c["result"] = "INVALID" if invalid else None
                except Exception as ex:
                    c["result"], c["failures"] = "INVALID", [{"type": "judge_exception",
                                                              "error": repr(ex)}]
                adhoc.append(c)
            else:
                c = new_case(cid, "UNKNOWN")
                c["result"] = "INVALID"
                c["failures"].append({"type": "unregistered_id",
                                      "detail": "behaviors 中出现注册表之外的 id"})
                adhoc.append(c)
        for cid in B_CASES + MUT_CASES + SPECIAL_CASES:
            if cases[cid]["result"] == "NOT_RUN" and cid not in by_id and not cases[cid]["info"].get("not_run_reason"):
                cases[cid]["info"]["not_run_reason"] = f"{bpath.name} 中无 {cid} 条目"

    # --- MR 路 ---
    mpath = actual_dir / f"mr_{tag}.json"
    base["inputs"]["mr_file"] = str(mpath) if mpath.exists() else None
    mraw, merr = load_json_file(mpath)
    if merr == "missing":
        for cid in MR_CASES:
            cases[cid]["info"]["not_run_reason"] = f"{mpath.name} 缺失"
        mraw = None
    elif merr or not isinstance(mraw, list):
        for cid in MR_CASES:
            c = cases[cid]
            c["result"] = "INVALID"
            c["failures"].append({"type": "mr_file_unreadable",
                                  "file": mpath.name, "error": merr or "顶层不是数组"})
        mraw = None

    if mraw is not None:
        m_by_id, m_dups = {}, {}
        for i, e in enumerate(mraw):
            if not isinstance(e, dict) or not isinstance(e.get("id"), str):
                c = new_case(f"MR-ENTRY-{i}", "MR")
                c["result"] = "INVALID"
                c["failures"].append({"type": "entry_missing_or_bad_id"})
                adhoc.append(c)
                continue
            cid = e["id"]
            if cid in m_by_id:
                m_dups.setdefault(cid, []).append(i)
            else:
                m_by_id[cid] = e
        for cid, e in m_by_id.items():
            if cid in cases:
                case = cases[cid]
                if cid in m_dups:
                    case["result"] = "INVALID"
                    case["failures"].append({"type": "duplicate_entry", "dup_indexes": m_dups[cid]})
                    continue
                try:
                    fails, info, invalid = judge_mr_entry(cid, e, actual_dir)
                    case["failures"], case["info"] = fails, {**case["info"], **info}
                    case["result"] = "INVALID" if invalid else None
                except Exception as ex:
                    case["result"] = "INVALID"
                    case["failures"].append({"type": "judge_exception", "error": repr(ex)})
            else:
                c = new_case(cid, "MR")
                c["result"] = "INVALID"
                c["failures"].append({"type": "unregistered_id",
                                      "detail": "mr 文件中出现注册表之外的 id"})
                adhoc.append(c)
        for cid in MR_CASES:
            if cases[cid]["result"] == "NOT_RUN" and cid not in m_by_id:
                cases[cid]["info"]["not_run_reason"] = f"{mpath.name} 中无 {cid} 条目"

    # --- 汇总 ---
    all_cases = [cases[cid] for cid in ALL_CASES] + adhoc
    for c in all_cases:
        if c["result"] is None:
            c["result"] = "FAIL" if c["failures"] else "PASS"
    grand = build_grand(all_cases)
    flat_failures = [{"case": c["id"], **f} for c in all_cases for f in c["failures"]]
    result = dict(base)
    result["cases"] = all_cases
    result["failures"] = flat_failures
    result["mutations"] = mutation_stats(all_cases)
    result["grand"] = grand
    result["caliber_echo"] = {k: v.get("class") for k, v in
                              ((caliber.get("comparisons") or {}).items())}
    result["assumptions_echo"] = (caliber.get("assumptions") or {})
    write_score(out_path, result)
    print_summary(result, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
