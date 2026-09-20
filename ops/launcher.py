# -*- coding: utf-8 -*-
"""明账 ClearLedger 图形启动器（打包为 启动明账.exe）

自举流水线：找 Python → 建 venv → 装依赖 → 演示数据 → 首次跑批 → 起门户 → 开浏览器。
等价于 docs/AI-点火指南.md 的 Step 1~6，给不用 agent 的用户一条双击路径。

打包（维护者执行，产物提交仓库根目录）：
    .venv/Scripts/python.exe -m pip install pyinstaller pillow
    .venv/Scripts/python.exe -c "from PIL import Image; img=Image.open('docs/assets/logo_B.png').convert('RGBA'); img.save('ops/launcher.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
    .venv/Scripts/python.exe -m PyInstaller --onefile --noconsole --name ClearLedgerLauncher \
        --icon ops/launcher.ico --workpath build --distpath dist ops/launcher.py
    mv dist/ClearLedgerLauncher.exe 启动明账.exe && rm -rf build dist ClearLedgerLauncher.spec

冒烟测试（无头，复用已有环境，杀 8620 并重启验证）：
    启动明账.exe --smoke     （开发态：python ops/launcher.py --smoke）
"""
from __future__ import annotations

import os
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

PORT = 8620
URL = f"http://127.0.0.1:{PORT}"
DEMO_INSTANCES = ("sales", "restaurant")
CREATE_NO_WINDOW = 0x08000000
DETACHED_FLAGS = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def repo_root() -> str:
    """exe 在仓库根目录；开发态脚本在 ops/ 下。"""
    base = sys.executable if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(base)
    if not os.path.isdir(os.path.join(root, "app")):
        root = base  # 兜底：开发态直接放根目录跑
    return root


def run(cmd: list[str], cwd: str, log, env: dict) -> tuple[int, str]:
    """跑子进程，实时把输出喂给 log，返回 (退出码, 尾部输出)。"""
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode("utf-8", errors="replace").rstrip()
        log(line)
        tail.append(line)
        if len(tail) > 40:
            tail.pop(0)
    return proc.wait(), "\n".join(tail)


def find_python(log) -> str | None:
    """优先 py 启动器，其次 PATH 里的 python。"""
    for candidate in (["py", "-3"], ["python"]):
        try:
            r = subprocess.run(
                candidate + ["--version"], capture_output=True, timeout=15,
                creationflags=CREATE_NO_WINDOW)
            if r.returncode == 0:
                ver = r.stdout.decode(errors="replace").strip() or r.stderr.decode(errors="replace").strip()
                log(f"[环境] 找到 {ver}（{'py -3' if candidate[0] == 'py' else 'python'}）")
                return candidate[0]
        except Exception:
            continue
    return None


def kill_port(log) -> None:
    """8620 被占则杀掉旧门户（手册故障 P-01 同款逻辑）。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             creationflags=CREATE_NO_WINDOW).stdout.decode(errors="replace")
    except Exception:
        return
    pids = {ln.split()[-1] for ln in out.splitlines()
            if f":{PORT}" in ln and "LISTENING" in ln.upper()}
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)
        log(f"[端口] 已结束占用 {PORT} 的旧进程 {pid}")


def portal_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/instance", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_portal(log, timeout=90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if portal_alive():
            return True
        time.sleep(1.5)
    return False


def bootstrap(log, force_demo: bool = False) -> str:
    """全流程，返回 'ok' 或错误描述。force_demo=True 时无论库文件在不在都重建演示数据。"""
    root = repo_root()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    venv_py = os.path.join(root, ".venv", "Scripts", "python.exe")
    venv_dbt = os.path.join(root, ".venv", "Scripts", "dbt.exe")

    # --- Step 1/2 环境 ---
    if not os.path.exists(venv_py):
        py = find_python(log)
        if py is None:
            return "未找到 Python（需要 3.11+）。请到 python.org 安装后重试。"
        log("[环境] 首次运行，创建虚拟环境并安装依赖（约 2~10 分钟，只需一次）…")
        code, tail = run([py, "-m", "venv", ".venv"], root, log, env)
        if code != 0:
            return f"创建虚拟环境失败：\n{tail[-600:]}"
    if not os.path.exists(venv_dbt):
        log("[环境] 安装依赖（dbt 体积较大，请耐心）…")
        code, tail = run([venv_py, "-m", "pip", "install", "-r", "requirements.txt"],
                         root, log, env)
        if code != 0 or not os.path.exists(venv_dbt):
            return f"依赖安装失败（可换清华镜像重试）：\n{tail[-600:]}"

    # --- Step 3/4 演示数据 + 首次跑批 ---
    missing = [i for i in DEMO_INSTANCES
               if not os.path.exists(os.path.join(root, "data", "warehouse", f"{i}.duckdb"))]
    if missing or force_demo:
        log("[数据] 生成演示数据（销售公司 + 连锁餐饮）…")
        for gen in ("sample_data/generate.py", "sample_data/generate_restaurant.py"):
            code, tail = run([venv_py, gen], root, log, env)
            if code != 0:
                return f"生成演示数据失败：\n{tail[-600:]}"
        for inst in DEMO_INSTANCES:
            log(f"[跑批] 账套 {inst}：摄取 → 编译 → dbt build…")
            code, tail = run([venv_py, "-m", "semantic.ingest_run", "--instance", inst], root, log, env)
            if code != 0:
                return f"[{inst}] 摄取失败：\n{tail[-600:]}"
            code, tail = run([venv_py, "-m", "semantic.compile_dbt", "--instance", inst], root, log, env)
            if code != 0:
                return f"[{inst}] 编译失败：\n{tail[-600:]}"
            pipe = os.path.join(root, "instances", inst, "pipeline")
            code, tail = run([venv_dbt, "build", "--profiles-dir", ".", "--no-use-colors"], pipe, log, env)
            if code != 0:
                return f"[{inst}] dbt build 失败：\n{tail[-600:]}"
            log(f"[跑批] 账套 {inst} 完成 ✓")
    else:
        log("[数据] 演示账套已有数据，跳过初始化")

    # --- Step 5/6 门户 ---
    log("[门户] 启动服务…")
    kill_port(log)
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    logf = open(os.path.join(root, "logs", "uvicorn.log"), "ab")
    subprocess.Popen(
        [venv_py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=root, env=env, stdout=logf, stderr=subprocess.STDOUT,
        creationflags=DETACHED_FLAGS, close_fds=True,
    )
    log(f"[门户] 等待 {URL} 就绪…")
    if not wait_portal(log):
        return f"门户 {URL} 未在 90 秒内就绪，详见 logs{os.sep}uvicorn.log"
    webbrowser.open(URL)
    return "ok"


# ---------------------------------------------------------------- tkinter UI
def gui() -> None:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("明账 ClearLedger · 启动器")
    root.geometry("640x460")
    root.minsize(560, 400)
    try:
        root.iconbitmap(os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher.ico")
                        if not getattr(sys, "frozen", False)
                        else os.path.join(os.path.dirname(sys.executable), "ops", "launcher.ico"))
    except Exception:
        pass

    title = tk.Label(root, text="明账 ClearLedger", font=("Microsoft YaHei UI", 16, "bold"))
    title.pack(pady=(14, 2))
    tk.Label(root, text="每个数字，表里如一 —— 私有化管理报表数据底座",
             fg="#64748B").pack(pady=(0, 8))

    logq: queue.Queue[str] = queue.Queue()
    box = scrolledtext.ScrolledText(root, height=14, font=("Consolas", 9), state="disabled",
                                    bg="#0F172A", fg="#E2E8F0")
    box.pack(fill="both", expand=True, padx=16, pady=6)

    status_var = tk.StringVar(value="就绪")
    bar = ttk.Progressbar(root, mode="indeterminate", length=340)
    bar.pack(pady=(0, 6))

    btns = tk.Frame(root)
    btns.pack(pady=(2, 12))

    def log(msg: str) -> None:
        logq.put(str(msg))

    def drain() -> None:
        try:
            while True:
                box.insert("end", logq.get_nowait() + "\n")
                box.see("end")
        except queue.Empty:
            pass
        root.after(200, drain)

    def worker(force_demo: bool) -> None:
        bar.start(24)
        status_var.set("正在初始化…")
        result = bootstrap(log, force_demo=force_demo)
        logq.put("[完成] " + ("门户已启动，浏览器即将打开。本窗口可以关闭，门户在后台继续运行。"
                             if result == "ok" else result))
        bar.stop()
        status_var.set("门户运行中 · 窗口可关闭" if result == "ok" else "初始化失败")
        if result != "ok":
            root.after(0, lambda: messagebox.showerror("明账启动器", result))
        else:
            open_btn.config(state="normal")

    def start(force_demo: bool = False) -> None:
        start_btn.config(state="disabled")
        rebuild_btn.config(state="disabled")
        threading.Thread(target=worker, args=(force_demo,), daemon=True).start()

    tk.Label(root, textvariable=status_var, fg="#2563EB").pack(pady=(0, 4))
    start_btn = tk.Button(btns, text="启动 / 初始化", width=16, command=lambda: start(False))
    start_btn.pack(side="left", padx=6)
    open_btn = tk.Button(btns, text="打开门户", width=12, state="normal",
                         command=lambda: webbrowser.open(URL))
    open_btn.pack(side="left", padx=6)

    def rebuild() -> None:
        if messagebox.askyesno("重建演示数据",
                               "将重新生成销售公司+连锁餐饮演示数据并覆盖其数据库。\n继续？"):
            start(force_demo=True)

    rebuild_btn = tk.Button(btns, text="重建演示数据", width=14, command=rebuild)
    rebuild_btn.pack(side="left", padx=6)

    drain()
    root.after(300, lambda: start(False))  # 打开即自动开始
    root.mainloop()


def smoke() -> int:
    """无头冒烟：复用已有环境走一遍门户启动链路。"""
    webbrowser.open = lambda *a, **k: None  # 测试态不真开浏览器
    root = repo_root()
    print(f"[smoke] repo_root={root}")
    lines: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        lines.append(str(msg))

    result = bootstrap(log)
    if result != "ok":
        print(f"[smoke] FAIL: {result}")
        return 1
    alive = portal_alive()
    print(f"[smoke] portal_alive={alive}")
    print("[smoke] PASS" if alive else "[smoke] FAIL: portal not alive")
    return 0 if alive else 1


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        sys.exit(smoke())
    gui()
