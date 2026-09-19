# -*- coding: utf-8 -*-
"""明账 ClearLedger — AI 装配线体检器（v0.4）

对新账套的投放区文件做标准化体检：列清单/推断类型/空值率/样例值/基数/异常值，
并起草 join 关系建议、维度与指标草案。产出：
  instances/<n>/onboarding/inspect_report.md   人类可读体检报告
  instances/<n>/onboarding/config_draft.yml    五配置草案（AI/人审核后转正）

用法：.venv/Scripts/python.exe -m semantic.inspect --instance <新账套名>
（前提：该账套 instance.yml 已建、inbox 已投放文件；sources.yml 可不存在——
体检器正是生成它的前置步骤）
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_any(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        for enc in ("utf-8-sig", "gbk"):
            try:
                return pd.read_csv(path, encoding=enc, dtype=str)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, engine="openpyxl", dtype=str)
    raise ValueError(f"不支持的文件类型: {path.name}")


def infer_type(s: pd.Series) -> str:
    v = s.dropna()
    if v.empty:
        return "string"
    sample = v.head(200)
    date_ok = 0
    for x in sample:
        try:
            pd.to_datetime(x)
            date_ok += 1
        except Exception:
            pass
    if date_ok / len(sample) > 0.9:
        return "date"
    num_ok = 0
    for x in sample:
        try:
            float(str(x).replace(",", ""))
            num_ok += 1
        except Exception:
            pass
    if num_ok / len(sample) > 0.9:
        return "decimal"
    return "string"


def profile_column(s: pd.Series) -> dict:
    v = s.fillna("__NULL__").astype(str).str.strip()
    nulls = int((v == "__NULL__").sum())
    nn = v[v != "__NULL__"]
    distinct = nn.nunique()
    t = infer_type(s)
    samples = [x[:30] for x in nn.drop_duplicates().head(3)]
    out = {"name": str(s.name), "type": t, "null_pct": round(nulls / max(len(s), 1) * 100, 1),
           "distinct": int(distinct), "samples": samples}
    if t != "string" and distinct == len(nn) and 0 < len(nn):
        # 疑似键列（数值型唯一列）
        out["likely_key"] = True
    elif t == "string" and distinct == len(nn) and len(nn) >= 3 and distinct >= 3:
        # 疑似键列（字符串型唯一列——编码类，键列的常见形态）
        out["likely_key"] = True
    if t == "string" and 0 < distinct <= 12:
        out["likely_enum"] = sorted(nn.unique().tolist())[:12]
    if t == "decimal":
        try:
            num = pd.to_numeric(nn.str.replace(",", ""), errors="coerce").dropna()
            out["min"] = round(float(num.min()), 4)
            out["max"] = round(float(num.max()), 4)
        except Exception:
            pass
    return out


def guess_entity(name_cn: str, cols: list[str]) -> str:
    """粗略猜测文件是事实表还是维表。中英文关键词 + 行数兜底由调用方补判"""
    kw = ["流水", "台账", "账单", "订单", "明细", "快照", "回款", "工时",
          "order", "ledger", "bill", "payment", "sales", "purchase", "stock",
          "snapshot", "flow", "transaction", "fact"]
    low = name_cn.lower()
    return "fact" if any(k in low for k in kw) else "dim"


def inspect_instance(name: str) -> dict:
    d = ROOT / "instances" / name
    if not (d / "instance.yml").exists():
        raise FileNotFoundError(f"实例不存在或缺 instance.yml: {d}")
    meta = yaml.safe_load((d / "instance.yml").read_text(encoding="utf-8"))
    inbox = (d / meta.get("inbox", "data/inbox")).resolve()
    title = meta.get("title", name)

    files = sorted([p for p in inbox.iterdir()
                    if p.suffix.lower() in (".csv", ".xlsx") and not p.name.startswith("~$")])
    profiles = {}
    for f in files:
        try:
            df = read_any(f)
            df.columns = [str(c).strip() for c in df.columns]
            profiles[f.name] = {
                "rows": len(df), "cols": [profile_column(df[c]) for c in df.columns],
                "entity": guess_entity(f.stem, list(df.columns)),
            }
        except Exception as e:
            profiles[f.name] = {"error": f"{type(e).__name__}: {e}"}

    facts = {k: v for k, v in profiles.items() if v.get("entity") == "fact"}
    dims = {k: v for k, v in profiles.items() if v.get("entity") == "dim"}
    # 兜底：若没有事实表，行数最大的文件视为事实表（英文文件名关键词漏判的最后防线）
    if not facts and profiles:
        biggest = max(profiles, key=lambda k: profiles[k].get("rows", 0))
        profiles[biggest]["entity"] = "fact"
        facts = {biggest: profiles[biggest]}
        dims = {k: v for k, v in profiles.items() if k != biggest}

    # join 建议：事实表列名与维表键列同名交叉（维表侧唯一即可，事实表侧是外键必然重复）
    join_suggestions = []
    for fn, fv in facts.items():
        fcols = {c["name"] for c in fv.get("cols", [])}
        for dn, dv in dims.items():
            dcols = {c["name"]: c for c in dv.get("cols", [])}
            shared = [c for c in fcols if c in dcols and dcols[c].get("likely_key")]
            for c in shared:
                join_suggestions.append(f"{fn} ←{c}— {dn}")

    # 起草五配置草案（yml 文本）
    draft = {"instance": meta, "sources_draft": [], "notes": []}
    for fn, fv in profiles.items():
        if "error" in fv:
            continue
        path = f"{fn.rsplit('_', 1)[0]}*.{'csv' if fn.endswith('.csv') else 'xlsx'}"
        fields = []
        for c in fv["cols"]:
            entry = {"cn": c["name"], "map": c["name"].lower().replace(" ", "_").replace("（", "").replace("）", ""), "type": c["type"]}
            if c.get("likely_key"):
                entry["required"] = True
            if c.get("likely_enum") and len(c["likely_enum"]) <= 10:
                entry["enum"] = c["likely_enum"]
                entry["level"] = "yellow"
            fields.append(entry)
        draft["sources_draft"].append({"name": fn.rsplit(".", 1)[0].rsplit("_", 1)[0],
                                       "title": fn.rsplit(".", 1)[0], "file_pattern": path,
                                       "fields": fields})
    draft_text = yaml.dump(draft, allow_unicode=True, sort_keys=False)

    report = {
        "instance": name, "title": title, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "files": list(profiles.keys()), "profiles": profiles,
        "join_suggestions": join_suggestions,
        "summary": {"files": len(files), "facts": len(facts), "dims": len(dims),
                    "total_rows": sum(v.get("rows", 0) for v in profiles.values())},
    }
    return report, draft_text


def write_report(name: str, report: dict, draft_text: str) -> tuple[Path, Path]:
    out_dir = ROOT / "instances" / name / "onboarding"
    out_dir.mkdir(parents=True, exist_ok=True)

    md = [f"# 装配体检报告 — {report['title']}", "",
          f"> 生成时间 {report['generated_at']} · 文件 {report['summary']['files']} 个 · "
          f"总行数 {report['summary']['total_rows']:,} · 事实表 {report['summary']['facts']} / 维表 {report['summary']['dims']}", "",
          "## 列画像", ""]
    for fname, fv in report["profiles"].items():
        if "error" in fv:
            md.append(f"### {fname} ❌ {fv['error']}")
            continue
        md.append(f"### {fname}（{fv['entity']}，{fv['rows']:,} 行）")
        md.append("")
        md.append("| 列 | 推断类型 | 空值率 | 基数 | 样例 | 备注 |")
        md.append("|---|---|---|---|---|---|")
        for c in fv["cols"]:
            note = []
            if c.get("likely_key"):
                note.append("疑似键列")
            if c.get("likely_enum"):
                note.append(f"枚举候选 {c['likely_enum'][:6]}")
            if "min" in c:
                note.append(f"范围 {c['min']}~{c['max']}")
            md.append(f"| {c['name']} | {c['type']} | {c['null_pct']}% | {c['distinct']} | "
                      f"{'、'.join(c['samples'][:2])} | {'；'.join(note)} |")
        md.append("")
    if report["join_suggestions"]:
        md.append("## 建议关联（同名键列交叉）")
        md.extend([f"- {j}" for j in report["join_suggestions"]])
        md.append("")
    md.append("## 五配置草案")
    md.append("见同目录 `config_draft.yml`（AI/人审核后转正为正式五配置）。")
    md.append("")
    md.append("**下一步（AI 装配 SOP）**：1) 审核/补全草案的 enum 与契约级别 "
              "2) 确认 join 键与主表 3) 补指标公式与报表定义 4) 转正五配置 → 跑三步链 → 红绿灯验收。")

    rp = out_dir / "inspect_report.md"
    rp.write_text("\n".join(md), encoding="utf-8")
    cp = out_dir / "config_draft.yml"
    cp.write_text(draft_text, encoding="utf-8")
    return rp, cp


def main() -> int:
    ap = argparse.ArgumentParser(description="装配线体检器：投放区文件 → 体检报告 + 五配置草案")
    ap.add_argument("--instance", required=True)
    args = ap.parse_args()
    try:
        report, draft_text = inspect_instance(args.instance)
        rp, cp = write_report(args.instance, report, draft_text)
    except FileNotFoundError as e:
        print(f"[fail] {e}", file=sys.stderr)
        return 2
    print(f"体检完成：{report['summary']['files']} 文件 / {report['summary']['total_rows']:,} 行")
    print(f"  报告 → {rp.relative_to(ROOT)}")
    print(f"  草案 → {cp.relative_to(ROOT)}")
    print(f"  join 建议 {len(report['join_suggestions'])} 条；下一步按报告末尾的装配 SOP 走")
    return 0


if __name__ == "__main__":
    sys.exit(main())
