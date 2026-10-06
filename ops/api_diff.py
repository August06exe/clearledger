# -*- coding: utf-8 -*-
"""API 前后对比工具：结构收纳/重构类改动的行为不变自证器。

用法：
  python internal/api_diff.py snap data/api_snapshots/before.json   # 拍快照
  python internal/api_diff.py diff before.json after.json              # 逐字比对
"""
import hashlib
import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8620"


def _get(path, headers=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return {"status": r.status, "len": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "body": body.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as e:
        body = e.read()
        return {"status": e.code, "len": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "body": body.decode("utf-8", errors="replace")}
    except Exception as exc:  # noqa: BLE001
        return {"status": -1, "error": repr(exc)}


def snapshot() -> dict:
    out = {}
    api_key = ""
    try:
        keys = json.load(open("data/openapi_keys.json", encoding="utf-8"))
        api_key = next(iter(keys)) if keys else ""
    except Exception:
        pass
    h = {"X-API-Key": api_key} if api_key else {}

    inst = json.loads(_get("/api/instance")["body"] or "{}").get("instance", "sales")
    out["/api/instance"] = _get("/api/instance")
    for p in ["/api/overview", "/api/lineage/graph", "/api/dictionary", "/api/aliases",
              "/api/reports", "/api/caliber", "/api/settings", "/api/runs", "/api/runs/status",
              f"/api/config/{inst}", f"/api/config/{inst}/pending", f"/api/config/{inst}/impact"]:
        out[p] = _get(p)

    reps_raw = json.loads(out["/api/reports"]["body"] or "[]")
    reps = reps_raw.get("reports") if isinstance(reps_raw, dict) else reps_raw
    key = None
    if isinstance(reps, list) and reps:
        key = reps[0].get("key") or reps[0]
        out[f"/api/reports/{key}/data"] = _get(f"/api/reports/{key}/data")
        exp = _get(f"/api/reports/{key}/export")
        exp.pop("body", None)  # 二进制只留哈希
        out[f"/api/reports/{key}/export"] = exp

    runs = json.loads(out["/api/runs"]["body"] or "[]")
    runs_list = runs.get("runs") if isinstance(runs, dict) else runs
    if isinstance(runs_list, list) and runs_list:
        rid = runs_list[0].get("run_id") or runs_list[0].get("id")
        for p in [f"/api/runs/{rid}", f"/api/runs/{rid}/gantt", f"/api/runs/{rid}/log"]:
            out[p] = _get(p)

    graph = json.loads(out["/api/lineage/graph"]["body"] or "{}")
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if isinstance(nodes, list) and nodes:
        uid = nodes[0].get("id") or nodes[0].get("uid")
        out[f"/api/node/{uid}"] = _get(f"/api/node/{uid}")

    dic_raw = json.loads(out["/api/dictionary"]["body"] or "{}")
    tables = dic_raw.get("tables") if isinstance(dic_raw, dict) else []
    name = None
    if isinstance(tables, list) and tables:
        t0 = tables[0]
        cols = t0.get("columns") if isinstance(t0, dict) else None
        if isinstance(cols, list) and cols:
            name = (cols[0].get("name") or cols[0].get("column")) if isinstance(cols[0], dict) else cols[0]
    if name:
        out[f"/api/lineage/columns/{name}"] = _get(f"/api/lineage/columns/{name}")

    for p in ["/api/open/reports", "/api/open/metrics", "/api/open/status"]:
        out[p] = _get(p, h)
    if key:
        out[f"/api/open/reports/{key}/data"] = _get(f"/api/open/reports/{key}/data", h)

    out["_meta"] = {"note": "POST 未快照（副作用）；export 只存哈希"}
    return out


def diff(a: dict, b: dict) -> int:
    bad = 0
    for k in sorted(set(a) | set(b)):
        if k.startswith("_"):
            continue
        va, vb = a.get(k), b.get(k)
        if va is None or vb is None:
            print(f"[缺失] {k}: {'后快照缺' if vb is None else '前快照缺'}")
            bad += 1
        elif va.get("sha256") != vb.get("sha256") or va.get("status") != vb.get("status"):
            print(f"[不同] {k} status {va.get('status')}→{vb.get('status')} len {va.get('len')}→{vb.get('len')}")
            print(f"   前: {str(va.get('body'))[:200]}")
            print(f"   后: {str(vb.get('body'))[:200]}")
            bad += 1
        else:
            print(f"[一致] {k}")
    print(f"\n结论：{'全部一致' if bad == 0 else f'{bad} 处不同'}")
    return bad


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "snap":
        path = sys.argv[2]
        data = snapshot()
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        ok = sum(1 for k, v in data.items() if not k.startswith("_") and v.get("status") == 200)
        print(f"快照 {len(data)-1} 条（{ok} 条 200）→ {path}")
    elif mode == "diff":
        a = json.load(open(sys.argv[2], encoding="utf-8"))
        b = json.load(open(sys.argv[3], encoding="utf-8"))
        sys.exit(1 if diff(a, b) else 0)
