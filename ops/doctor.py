# -*- coding: utf-8 -*-
"""明账 ClearLedger — 系统自检（AI/人类通用）

用法：
  .venv/Scripts/python.exe ops/doctor.py          # 人类可读表格
  .venv/Scripts/python.exe ops/doctor.py --json   # 机器可读（agent 巡检用）

检查项覆盖：环境 / 数据仓库 / 投放区 / 跑批历史 / 门户端口 / 配置 / 静态资源。
输出三级：ok（健康）/ warn（可用但需注意）/ fail（需处置，见 docs/AI-操作手册.md §4）。
退出码：0=全部 ok（含 warn）；1=存在 fail。
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results: list[dict] = []


def check(name: str, status: str, detail: str) -> None:
    results.append({"check": name, "status": status, "detail": detail})


def main() -> int:
    # ---- 1. 环境 ----
    try:
        import duckdb, fastapi, apscheduler, sqlglot  # noqa: F401
        check("python 依赖", "ok", "duckdb/fastapi/apscheduler/sqlglot 可导入")
    except Exception as e:
        check("python 依赖", "fail", f"导入失败：{e}（重装：.venv/Scripts/python -m pip install -r requirements.txt）")

    dbt_exe = ROOT / ".venv" / "Scripts" / "dbt.exe"
    check("dbt 可执行", "ok" if dbt_exe.exists() else "fail",
          str(dbt_exe.relative_to(ROOT)) if dbt_exe.exists() else "不存在（重装 dbt-duckdb）")

    for f in ("app/static/vendor/echarts.min.js", "app/static/vendor/g6.min.js"):
        p = ROOT / f
        check(f"前端库 {f.split('/')[-1]}", "ok" if p.exists() and p.stat().st_size > 100_000 else "fail",
              f"{p.stat().st_size // 1024} KB" if p.exists() else "缺失（页面会崩，需重新下载到 vendor/）")

    # ---- 2. 数据仓库 ----
    wh = ROOT / "data" / "warehouse" / "warehouse.duckdb"
    if not wh.exists():
        check("数据仓库", "fail", "warehouse.duckdb 不存在（跑一次 重建演示数据.bat 或 ingest+dbt build）")
    else:
        wal = wh.with_suffix(".duckdb.wal")
        try:
            import duckdb
            con = duckdb.connect(str(wh), read_only=True)
            rows = con.execute(
                "select table_schema, count(*) from information_schema.tables "
                "where table_schema in ('raw','staging','intermediate','marts') group by 1 order by 1"
            ).fetchall()
            latest = con.execute(
                "select max(month) from marts.mart_kpi_monthly"
            ).fetchone()[0]
            con.close()
            detail = " / ".join(f"{s}:{n}" for s, n in rows)
            if latest is not None:
                detail += f"；最新数据月 {latest}"
            check("数据仓库", "ok" if rows else "warn", f"{wh.stat().st_size // 1024 // 1024} MB，{detail}")
            if wal.exists():
                check("WAL 文件", "warn", "存在未 checkpoint 的 .wal——备份时必须连它一起拷（备份数据.bat 已处理）")
        except Exception as e:
            check("数据仓库", "fail", f"无法只读打开：{e}（可能跑批进行中或文件损坏）")

    # ---- 3. 投放区 vs 声明的数据源 ----
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "ingest" / "sources.yml").read_text(encoding="utf-8"))
        inbox = ROOT / "data" / "inbox"
        missing = []
        for src in cfg.get("sources", []):
            found = False
            for pat in src.get("files", []):
                if any(inbox.glob(pat)):
                    found = True
                    break
            if not found:
                missing.append(f"{src['name']}({','.join(src.get('files', []))})")
        if missing:
            check("投放区", "fail", "缺少声明文件：" + "；".join(missing) + "（跑批会红灯）")
        else:
            check("投放区", "ok", f"{len(cfg.get('sources', []))} 个数据源文件齐全")
    except Exception as e:
        check("投放区", "fail", f"sources.yml 解析失败：{e}")

    # ---- 4. 跑批历史 ----
    hist = ROOT / "data" / "runs" / "history.json"
    if not hist.exists():
        check("跑批历史", "warn", "尚无跑批记录（新装属正常，跑一次批即可）")
    else:
        try:
            runs = json.loads(hist.read_text(encoding="utf-8"))
            last = runs[0] if runs else None
            if not last:
                check("跑批历史", "warn", "history.json 为空")
            else:
                st = last.get("status")
                note = {"green": "全绿", "yellow": "黄灯（存在数据质量告警，看 /api/overview 的 warnings 明细）",
                        "red": "红灯！按手册 §4 排障"}.get(st, st)
                check("最近跑批", "ok" if st in ("green", "yellow") else "fail",
                      f"{last.get('finished_at')} · {st} · {note} · 触发:{last.get('trigger')}")
        except Exception as e:
            check("跑批历史", "warn", f"history.json 解析失败：{e}")

    # ---- 5. 门户端口 ----
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", 8620))
        check("门户端口 8620", "ok", "门户在运行")
    except Exception:
        check("门户端口 8620", "warn", "门户未运行（双击 启动明账.bat，或手册 R-07）")
    finally:
        s.close()

    # ---- 6. 配置文件 ----
    st_file = ROOT / "data" / "settings.json"
    if st_file.exists():
        try:
            st_cfg = json.loads(st_file.read_text(encoding="utf-8"))
            mode = "定时 " + f"{st_cfg.get('schedule_hour', 6):02d}:{st_cfg.get('schedule_minute', 30):02d}" \
                if st_cfg.get("schedule_enabled") else "完全手动（默认）"
            check("跑批模式", "ok", mode)
        except Exception:
            check("跑批模式", "warn", "settings.json 损坏，将回退默认（手动）")
    else:
        check("跑批模式", "ok", "未自定义（默认完全手动）")

    idx = ROOT / "app" / "static" / "index.html"
    if idx.exists():
        html = idx.read_text(encoding="utf-8")
        n = html.count("?v=")
        check("前端缓存版本号", "ok" if n >= 7 else "warn",
              f"{n} 处 ?v= 参数（改前端静态文件时必须同步升级，否则浏览器用旧缓存）")

    for f in ("pipeline/target/manifest.json", "pipeline/target/run_results.json"):
        check(f"dbt 产物 {f.split('/')[-1]}", "ok" if (ROOT / f).exists() else "warn",
              "就绪" if (ROOT / f).exists() else "不存在（跑一次 dbt build 自动生成；血缘/字典页会降级）")

    # ---- 7. 语义层实例（v0.3）----
    try:
        from semantic.loader import list_instances, load_instance
        names = list_instances()
        if not names:
            check("语义层实例", "warn", "instances/ 下无实例（v0.3 语义层未启用）")
        for n in names:
            try:
                inst = load_instance(n)
                db = (inst.pipeline_dir / inst.db_path).resolve()
                check(f"实例 {n}", "ok" if db.exists() else "warn",
                      f"五配置校验通过 · {len(inst.dashboard.get('reports', []))} 张报表 · "
                      f"库{'就绪' if db.exists() else '未建（跑 ingest+dbt build）'}")
            except Exception as e:
                check(f"实例 {n}", "fail", f"配置校验失败：{e}")
    except Exception as e:
        check("语义层实例", "warn", f"检查跳过：{e}")

    # ---- 输出 ----
    overall = "fail" if any(r["status"] == "fail" for r in results) else "ok"
    if "--json" in sys.argv:
        print(json.dumps({"overall": overall, "results": results}, ensure_ascii=False, indent=1))
    else:
        icon = {"ok": "✅", "warn": "⚠️ ", "fail": "❌"}
        print("=" * 62)
        print(" 明账 ClearLedger 自检")
        print("=" * 62)
        for r in results:
            print(f" {icon[r['status']]} {r['check']:<14s} {r['detail']}")
        print("=" * 62)
        print(f" 结论：{'存在 FAIL 项，按 docs/AI-操作手册.md §4 处置' if overall == 'fail' else '系统健康'}")
    return 1 if overall == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
