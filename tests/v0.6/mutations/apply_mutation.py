# -*- coding: utf-8 -*-
"""变异体注入工具（测试装备校正用）

用法（在仓库根目录）：
    python tests/v0.6/mutations/apply_mutation.py M1   # 产出 build/_mut_M1/
    cd build/_mut_M1 && ../../../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8630
探针结束后：删除 build/_mut_M1/ 即完成恢复（真实仓库未被改动）。

原理：把 app/ semantic/ instances/_wb_r1/（若存在）最小拷贝到 build/_mut_<id>/，
对副本 app/services/config_workbench.py 应用该变异体的文本替换，打印启动命令。
变异体定义见同目录 MUTATIONS.json（旧串必须唯一命中，否则报错拒改）。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

MUT_ROOT = Path(__file__).resolve().parent
REPO = MUT_ROOT.parents[2]
BUILD = REPO / "build"
COPY_DIRS = ["app", "semantic"]
OPTIONAL_DIRS = ["tests/fixtures/instances/_wb_r1", "tests/fixtures/instances/_wb_r2", "tests/fixtures/instances/_wb_r3"]


def main() -> int:
    mid = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = json.loads((MUT_ROOT / "MUTATIONS.json").read_text(encoding="utf-8"))
    if mid not in spec:
        print(f"未知变异体 {mid!r}，可选：{sorted(spec)}")
        return 1
    m = spec[mid]
    dest = BUILD / f"_mut_{mid}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for d in COPY_DIRS:
        shutil.copytree(REPO / d, dest / d)
    for d in OPTIONAL_DIRS:
        if (REPO / d).exists():
            shutil.copytree(REPO / d, dest / d)
    (dest / "data").mkdir(exist_ok=True)

    target = dest / m["file"]
    text = target.read_text(encoding="utf-8")
    pairs = [(m["old"], m["new"])]
    if m.get("old2"):
        pairs.append((m["old2"], m["new2"]))
    for old, new in pairs:
        n = text.count(old)
        if n != 1:
            print(f"[{mid}] 注入失败：旧串命中 {n} 次（应为 1）。实现可能已变化，需更新 MUTATIONS.json。")
            return 1
        text = text.replace(old, new)
    target.write_text(text, encoding="utf-8")
    print(f"[{mid}] 已注入：{m['desc']}")
    print(f"[{mid}] 副本位置: {dest}")
    print(f"[{mid}] 启动: cd \"{dest}\" && \"{REPO}/.venv/Scripts/python.exe\" -m uvicorn app.main:app --port 8630")
    return 0


if __name__ == "__main__":
    sys.exit(main())
