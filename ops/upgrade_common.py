# -*- coding: utf-8 -*-
"""明账 ClearLedger — 升级面共用判定（纯标准库）

三个入口共用，一处实现（无损升级方案 4 节落点 7f：「与 upgrade.py 共用判定」）：
  ops/upgrade.py   通道/布局探测、版本语义、依赖指纹、Release 查询（plan/preflight/smoke/rollback）
  ops/doctor.py    体检 a（依赖比对）/ d（版本偏差）/ f（布局与通道）
  ops/launcher.py  bootstrap 的依赖指纹刷新（R2）与两件套版本比对（R11）

编码约束：本模块只允许标准库——upgrade.py 的 migrate/switch/rollback 由 py -3
（系统 Python 3.8+）执行且会 import 本模块；禁止顶层引入 duckdb/yaml 等 venv 包，
也禁止 is_relative_to 等 3.9+ API。
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

RELEASES_API = "https://api.github.com/repos/August06exe/clearledger/releases"
_HTTP_TIMEOUT = 10


class UpgradeError(Exception):
    """升级面可预期失败（人类可读原因；upgrade.py 会把它收敛成 JSON 状态）。
    lines：失败前已积累的人类可读行（如 sync 的冲突对账指引）——upgrade.py 的
    main 会一并输出，不许吞掉。"""

    def __init__(self, msg: str, lines: list[str] | None = None) -> None:
        super().__init__(msg)
        self.lines = list(lines) if lines else None


# ---------------------------------------------------------------- 版本语义（6.1）

_SEMVER_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def parse_semver(value: str) -> tuple[int, int, int]:
    m = _SEMVER_RE.match(value or "")
    if not m:
        raise UpgradeError(f"版本串 {value!r} 不符合 vX.Y.Z 语义（6.1：语义化 tag 是唯一升级单位）")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def semver_cmp(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return (a > b) - (a < b)


def read_local_version(root: Path) -> str:
    """仓库根 VERSION（一行纯文本）——版本单一出处（方案 4 节落点 2）。"""
    return (Path(root) / "VERSION").read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------- 通道与布局（3.1）

def detect_channel_layout(root: Path) -> dict:
    """通道 G/Z 与模式 A/B 探测；两不像即 fail，禁止猜（3.1）。
    通道 G = 产品根有 .git（git 双仓制）；通道 Z = 无 .git（zip 槽位换名）；
    模式 A = instances/ 与 data/ 都在产品根内；模式 B = 都不在（平级分离）。"""
    root = Path(root)
    has_git = (root / ".git").exists()
    has_inst = (root / "instances").is_dir()
    has_data = (root / "data").is_dir()
    if has_inst and has_data:
        mode = "A"
    elif not has_inst and not has_data:
        mode = "B"
    else:
        mode = "unknown"
    channel = "G" if has_git else "Z"
    detail = [f".git={'有' if has_git else '无'}→通道{channel}",
              f"instances/={'在根内' if has_inst else '不在'}、data/={'在根内' if has_data else '不在'}"
              f"→模式{mode}"]
    ok = mode != "unknown"
    if not ok:
        detail.append("探测不明（instances/ 与 data/ 只有一个在产品根内）——按 3.1 直接 fail，禁止猜")
    return {"ok": ok, "channel": channel, "mode": mode, "detail": detail}


def window_mode(root: Path, staging: Path | None = None) -> str:
    """停机窗中段视角（upgrade.py 的 migrate/switch 用）：migrate 之后、switch 之前，
    data/ 已在 staging 而 instances/ 仍在旧根——3.2 时序的合法中间态，视同模式 A。"""
    root = Path(root)
    inst_in = (root / "instances").is_dir()
    data_in = (root / "data").is_dir()
    if inst_in and data_in:
        return "A"
    if not inst_in and not data_in:
        return "B"
    ups = root.parent / "upgrade"
    stagings = ([staging] if staging is not None else
                sorted(ups.glob("staging-v*")) if ups.is_dir() else [])
    if inst_in and any((s / "data").is_dir() for s in stagings):
        return "A"  # 窗口中间态：data 已搬入 staging
    return "unknown"


def data_dir(root: Path, layout: dict | None = None) -> Path:
    """data/ 定位：模式 A 在产品根内；模式 B 在产品根平级（3.1 决策图形态）。
    防污染纪律：任何探测/留档写盘都经本函数——绝不允许在模式 B 或探测不明的根里
    凭空造出 root/data（会把布局探测悄悄翻转成模式 A）。"""
    root = Path(root)
    layout = layout or detect_channel_layout(root)
    if layout["mode"] == "B":
        return root.parent / "data"
    return root / "data"


# ---------------------------------------------------------------- 依赖指纹（requirements 区间核对）

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(\[[^\]]*\])?\s*(.*)$")


def parse_requirements(root: Path) -> list[tuple[str, str]]:
    """解析 requirements.txt（上界锁定区间，5.1）→ [(包名, 规格串)]。"""
    req = Path(root) / "requirements.txt"
    out: list[tuple[str, str]] = []
    for line in req.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = _REQ_LINE.match(line)
        out.append((m.group(1), m.group(3).strip()) if m else (line, "<解析失败>"))
    return out


def _ver_tuple(v: str) -> tuple:
    """宽容版本比较键：按 ./- 切段，数字段转 int，其余保字符串。"""
    parts = [p for p in re.split(r"[.\-]", v.strip()) if p != ""]
    return tuple(int(p) if p.isdigit() else p for p in parts)


def spec_ok(installed: str, spec: str) -> tuple[bool, str]:
    """区间核对。支持子句：>=, <=, ==, !=, >, <（requirements.txt 现役写法全覆盖）。"""
    if not spec.strip():
        return True, ""
    for m in re.finditer(r"(>=|<=|==|!=|>|<)\s*([0-9A-Za-z.\-]+)", spec):
        op, want = m.group(1), m.group(2)
        try:
            a, b = _ver_tuple(installed), _ver_tuple(want)
        except Exception as exc:
            return False, f"版本串解析失败（{exc}）"
        if all(isinstance(x, int) for x in a) and all(isinstance(x, int) for x in b):
            n = max(len(a), len(b))
            a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
        try:
            ok = {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b,
                  "==": a == b, "!=": a != b}[op]
        except TypeError:
            return False, f"版本串不可比较：{installed} {op} {want}"
        if not ok:
            return False, f"installed={installed} 不满足 {op}{want}"
    return True, ""


def installed_versions_local(names: list[str]) -> dict[str, str | None]:
    """当前解释器已装版本（调用方必须运行在待检环境内——doctor/upgrade 即 venv）。"""
    import importlib.metadata as _md
    out: dict[str, str | None] = {}
    for n in names:
        try:
            out[n] = _md.version(n)
        except _md.PackageNotFoundError:
            out[n] = None
    return out


def installed_versions_via(python_exe: str | Path, names: list[str]) -> dict[str, str | None]:
    """经 subprocess 探测另一解释器的已装版本——launcher 的 exe 进程看不到 venv 的
    site-packages，必须打进去问（R2 指纹比对在 exe 侧的唯一正确取法）。"""
    probe = ("import importlib.metadata,json,sys;"
             "d={};\n"
             "for n in json.loads(sys.argv[1]):\n"
             "    try: d[n]=importlib.metadata.version(n)\n"
             "    except Exception: d[n]=None\n"
             "print(json.dumps(d))")
    try:
        r = subprocess.run([str(python_exe), "-c", probe, json.dumps(names)],
                           capture_output=True, timeout=120)
        got = json.loads(r.stdout.decode("utf-8", errors="replace"))
        return {n: got.get(n) for n in names}
    except Exception:
        return {n: None for n in names}


def dependency_check(root: Path, python_exe: str | Path | None = None) -> tuple[list[dict], bool]:
    """installed 对 requirements.txt 的核对。python_exe=None 用当前解释器（venv 内
    调用方：doctor / upgrade 的 smoke 与 rollback）；传入解释器路径则 subprocess
    探测（launcher 的 exe 侧）。返回（逐项结果， 全过与否）。"""
    root = Path(root)
    req = root / "requirements.txt"
    if not req.is_file():
        return [{"name": "requirements.txt", "ok": False, "note": "文件缺失"}], False
    pairs = parse_requirements(root)
    names = [n for n, _ in pairs]
    installed = (installed_versions_local(names) if python_exe is None
                 else installed_versions_via(python_exe, names))
    results, all_ok = [], True
    for name, spec in pairs:
        ver = installed.get(name)
        if ver is None:
            results.append({"name": name, "required": spec or "(任意)", "ok": False, "note": "未安装"})
            all_ok = False
            continue
        ok, note = spec_ok(ver, spec)
        results.append({"name": name, "required": spec or "(任意)", "installed": ver,
                        "ok": ok, "note": note})
        all_ok = all_ok and ok
    return results, all_ok


# ---------------------------------------------------------------- Release 查询（6.4 发现通道）

def _http_get(url: str, timeout: int = _HTTP_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "clearledger-upgrade/0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_latest_release(timeout: int = _HTTP_TIMEOUT) -> dict:
    """Releases latest（HTTPS 免鉴权）。无 Release 时 GitHub 返回 404。"""
    try:
        return json.loads(_http_get(f"{RELEASES_API}/latest", timeout).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpgradeError(f"查询 Releases latest 失败：HTTP {exc.code}（{exc.reason}）——"
                           f"仓库尚无 Release 或网络不通")
    except Exception as exc:
        raise UpgradeError(f"查询 Releases latest 失败：{exc}")


def fetch_release_tags(timeout: int = _HTTP_TIMEOUT) -> list[str]:
    """列 Release tag（plan 的中间版本清单用；失败容忍，返回空）。"""
    try:
        data = json.loads(_http_get(f"{RELEASES_API}?per_page=100", timeout).decode("utf-8"))
        return [r.get("tag_name", "") for r in data if r.get("tag_name")]
    except Exception:
        return []
