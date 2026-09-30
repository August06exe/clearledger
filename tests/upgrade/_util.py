# -*- coding: utf-8 -*-
"""tests/upgrade 共用夹具与工具。

被测对象：ops/backup.py 与 ops/upgrade.py（规格 internal/docs/
无损升级架构方案-20260930.md 3.3/4 节）。ops/ 不是包，这里把 ops/ 挂进
sys.path 后按模块名导入（与 upgrade.py 自身 `from upgrade_common import`
的执行期取法一致）。所有夹具落 tempfile 临时目录，绝不触碰仓库 data/
与真实账套。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = REPO_ROOT / "ops"
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

import backup           # noqa: E402 —— ops/backup.py
import upgrade          # noqa: E402 —— ops/upgrade.py
import upgrade_common   # noqa: E402 —— ops/upgrade_common.py


# ---------------------------------------------------------------- 基础件

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_bytes(path: Path, data: bytes) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def write_text(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_duckdb_file(path: Path) -> Path:
    """真实金库文件（只读体检可过）。测试跑在 .venv 解释器内，duckdb 可用。"""
    import duckdb
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("create schema raw; create table raw.t as select 42 as v")
    con.close()
    return path


def full_manifest(**overrides) -> dict:
    """6.2 的十四字段合法 manifest 模板（sha256 等以格式合法的伪值填满）。"""
    m = {
        "version": "v0.7.0",
        "min_upgradable_from": "v0.6.0",
        "zip_sha256": "a" * 64,
        "requirements_sha256": "b" * 64,
        "duckdb_version": "1.3.2",
        "tenants_builtin": ["sales", "restaurant"],
        "launcher_rebuilt": False,
        "mart_schema_changed": False,
        "config_schema_version": {"instance_yml": 1, "settings": 1},
        "contract_version": 1,
        "contract_changes": [],
        "sentinel_reports": ["region_month"],
        "auto_apply": False,
        "requires_manual_steps": [],
    }
    m.update(overrides)
    return m


def make_product_root(base: Path, *, version: str = "v0.6.0",
                      with_git: bool = False, with_warehouse: bool = True,
                      with_runs: bool = False, with_logs: bool = False) -> Path:
    """最小可判布局的产品根（模式 A：instances/ 与 data/ 都在根内）。"""
    root = Path(base) / "root"
    write_text(root / "VERSION", version + "\n")
    write_text(root / "requirements.txt", "# fixture\n")
    inst = root / "instances" / "acme"
    for fname in ("instance.yml", "sources.yml", "wide.yml",
                  "dimensions.yml", "metrics.yml", "dashboard.yml"):
        write_text(inst / fname, f"# {fname}\n")
    write_text(inst / "data" / "inbox" / "f.csv", "a,b\n1,2\n")  # 2.3 第一行持久资产
    write_text(inst / "onboarding" / "config_history" / "20260101.json", "{}\n")
    (root / "data" / "warehouse").mkdir(parents=True, exist_ok=True)
    if with_warehouse:
        write_bytes(root / "data" / "warehouse" / "acme.duckdb", b"fake-quack")
    if with_runs:
        write_text(root / "data" / "runs" / "history_acme.json", "[]\n")
    if with_logs:
        write_text(root / "logs" / "x.log", "log\n")
    if with_git:
        (root / ".git").mkdir(parents=True, exist_ok=True)  # 探测只看存在性
    return root


# ---------------------------------------------------------------- 运行器

def run_backup_main(argv: list[str]) -> tuple[int, str, str]:
    """同进程跑 backup.main(argv)，捕获输出。返回 (rc, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = backup.main(argv)
    return rc, out.getvalue(), err.getvalue()


def run_upgrade_main(argv: list[str], chdir: Path | None = None):
    """同进程跑 upgrade.main(argv)，捕获输出。

    返回 (rc, stdout, stderr, payload)——payload 为末行机器 JSON（无则 None）。
    """
    out, err = io.StringIO(), io.StringIO()
    old_cwd = None
    if chdir is not None:
        old_cwd = os.getcwd()
        os.chdir(chdir)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = upgrade.main(argv)
    finally:
        if old_cwd is not None:
            os.chdir(old_cwd)
    payload = None
    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    if lines:
        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(lines[-1])
    return rc, out.getvalue(), err.getvalue(), payload


# ---------------------------------------------------------------- git 夹具

_GIT_ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull}


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """跑一条 git（隔离全局配置，避免宿主机 gpgsign/模板干扰夹具提交）。"""
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                       timeout=180, env=_GIT_ENV)
    if check and r.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} 失败（exit {r.returncode}）："
            + r.stderr.decode("utf-8", errors="replace"))
    return r


def git_clone(src: Path, dst: Path) -> None:
    r = subprocess.run(["git", "clone", str(src), str(dst)], capture_output=True,
                       timeout=180, env=_GIT_ENV)
    if r.returncode != 0:
        raise AssertionError(
            f"git clone 失败：{r.stderr.decode('utf-8', errors='replace')}")


class TempDirCase(unittest.TestCase):
    """每个用例独立临时目录的基类（self.base 为夹具根）。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cl_upgrade_test_")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
