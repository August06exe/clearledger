# -*- coding: utf-8 -*-
"""ops/upgrade.py 回滚情形判定与恢复测试（3.3 步骤十）。

情形判定的契约（主证据=快照指纹实测，history 仅辅助）：
  - 金库 size 或 mtime 任一偏离 backup_manifest 记录 → 情形 B（先恢复快照再换回）
  - schedule_enabled=true（状态机 smoke 记录或 settings.json）→ 一律情形 B
  - finalize 已跑 → 必然情形 B（Gitea 铁律）
  - 指纹一致且定时关闭且未 finalize → 情形 A（直接换回）

夹具模拟通道 Z switch 之后的现场（upgrade/prev-v0.6.0 旧根 + 产品根新根，
state.json 与快照都在新根 data/ 内），全部临时目录纯文件操作；不碰仓库
data/ 与真实账套。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from _util import (TempDirCase, git, make_product_root, sha256_file, upgrade,
                   write_bytes, write_text)

DB_BYTES = b"ACME-GOLD-VAULT-BYTES-0123456789"


def _post_switch_zone(base: Path, *, live_bytes: bytes | None = None,
                      live_mtime_shift: float | None = None,
                      settings_schedule: bool = False,
                      smoke_schedule: bool | None = None,
                      finalize_ran: bool = False):
    """构造 switch 后的通道 Z 现场，返回 (root, prev, snap)。

    live_bytes=None 且 live_mtime_shift=None → 在用金库与快照逐字节相同、
    size/mtime 一致（情形 A 的判定输入）。
    """
    zone = base / "zone"
    prev = zone / "upgrade" / "prev-v0.6.0"
    write_text(prev / "VERSION", "v0.6.0\n")
    write_text(prev / "requirements.txt", "# old\n")
    write_text(prev / "app" / "main.py", "# old code\n")

    root = zone / "root"  # switch 后的产品根（新版）
    write_text(root / "VERSION", "v0.7.0\n")
    write_text(root / "requirements.txt", "# new\n")
    write_text(root / ".venv" / "Scripts" / "keep.txt", "venv\n")
    write_text(root / "logs" / "uvicorn.log", "log\n")
    write_text(root / "instances" / "acme" / "instance.yml", "name: acme\n")

    snap = root / "data" / "backup" / "pre-upgrade-v0.6.0-v0.7.0-20260930_1200"
    snap_db = write_bytes(snap / "data" / "warehouse" / "acme.duckdb", DB_BYTES)
    write_text(snap / "data" / "settings.json",
               json.dumps({"instance": "acme", "schedule_enabled": False}))
    write_text(snap / "VERSION", "v0.6.0\n")
    write_text(snap / "requirements.txt", "# old\n")

    # backup_manifest：三字段指纹取快照侧实测（与 ops/backup.py 记录口径一致）
    rels = ("data/warehouse/acme.duckdb", "data/settings.json",
            "VERSION", "requirements.txt")
    files = [{"path": rel, "sha256": sha256_file(snap / rel),
              "size": (snap / rel).stat().st_size,
              "mtime": (snap / rel).stat().st_mtime} for rel in rels]
    write_text(snap / "backup_manifest.json", json.dumps(
        {"format": "clearledger-backup-manifest/1", "kind": "upgrade-snapshot",
         "tag": "pre-upgrade-v0.6.0-v0.7.0", "files": files, "failed": [],
         "totals": {"files": len(files), "bytes": sum(f["size"] for f in files)}}))

    # 在用金库：升级窗口内可能已被新代码写过
    live_db = write_bytes(root / "data" / "warehouse" / "acme.duckdb",
                          DB_BYTES if live_bytes is None else live_bytes)
    base_mtime = snap_db.stat().st_mtime
    mtime = base_mtime if live_mtime_shift is None else base_mtime + live_mtime_shift
    os.utime(live_db, (mtime, mtime))

    write_text(root / "data" / "settings.json",
               json.dumps({"instance": "acme", "schedule_enabled": settings_schedule}))

    steps = ["stop", "backup", "migrate", "switch"]
    if finalize_ran:
        steps.append("finalize")
    prog = {"started_at": "2026-09-30T12:00:00", "channel": "Z", "mode": "A",
            "from": "v0.6.0", "target": "v0.7.0", "steps": steps,
            "backup": {"at": "2026-09-30T12:01:00", "snapshot_dir": str(snap),
                       "manifest": str(snap / "backup_manifest.json")},
            "switch": {"from": "v0.6.0", "to": "v0.7.0", "at": "2026-09-30T12:05:00",
                       "prev_dir": str(prev)}}
    if smoke_schedule is not None:
        prog["smoke"] = {"at": "2026-09-30T12:06:00",
                         "schedule_enabled": smoke_schedule}
    state = {"format": "clearledger-upgrade-state/1",
             "last_plan": {"target": "v0.7.0",
                           "manifest": {"tenants_builtin": ["sales"]}},
             "in_progress": prog}
    write_text(root / "data" / "upgrade" / "state.json", json.dumps(state))
    return root, prev, snap


def _mid_window_zone(base: Path, *, staging_db_bytes: bytes | None = None):
    """migrate 后、switch 前的通道 Z 现场（红队 B1）：data/ 整体（含快照与
    状态机）已搬入 staging 侧；backup.snapshot_dir 记录的是搬迁前的 root 侧
    绝对路径（回搬后才重新有效——这正是 B1 要先逆向搬回的原因之一）。"""
    zone = base / "zone2"
    staging = zone / "upgrade" / "staging-v0.7.0"
    write_text(staging / "VERSION", "v0.7.0\n")
    write_text(staging / "app" / "main.py", "# new code\n")

    root = zone / "root"  # 旧根：代码与 builtin 还在，data/ 已搬走（无 root/data）
    write_text(root / "VERSION", "v0.6.0\n")
    write_text(root / "requirements.txt", "# old\n")
    write_text(root / "instances" / "acme" / "instance.yml", "name: acme\n")

    snap = staging / "data" / "backup" / "pre-upgrade-v0.6.0-v0.7.0-20260930_1200"
    snap_db = write_bytes(snap / "data" / "warehouse" / "acme.duckdb", DB_BYTES)
    write_text(snap / "data" / "settings.json",
               json.dumps({"instance": "acme", "schedule_enabled": False}))
    write_text(snap / "VERSION", "v0.6.0\n")
    write_text(snap / "requirements.txt", "# old\n")
    rels = ("data/warehouse/acme.duckdb", "data/settings.json",
            "VERSION", "requirements.txt")
    files = [{"path": rel, "sha256": sha256_file(snap / rel),
              "size": (snap / rel).stat().st_size,
              "mtime": (snap / rel).stat().st_mtime} for rel in rels]
    write_text(snap / "backup_manifest.json", json.dumps(
        {"format": "clearledger-backup-manifest/1", "kind": "upgrade-snapshot",
         "tag": "pre-upgrade-v0.6.0-v0.7.0", "files": files, "failed": [],
         "totals": {"files": len(files), "bytes": sum(f["size"] for f in files)}}))

    live_db = write_bytes(staging / "data" / "warehouse" / "acme.duckdb",
                          DB_BYTES if staging_db_bytes is None else staging_db_bytes)
    mtime = snap_db.stat().st_mtime
    os.utime(live_db, (mtime, mtime))  # rename 保 mtime：指纹一致 → 情形 A 判定输入
    write_text(staging / "data" / "settings.json",
               json.dumps({"instance": "acme", "schedule_enabled": False}))

    # 意图字节数口径：data/ 树排除 data/upgrade（与 ops/upgrade.py _item_bytes 一致）
    total = 0
    for d, dns, fns in os.walk(staging / "data"):
        dns[:] = [n for n in dns if (Path(d) / n) != staging / "data" / "upgrade"]
        for f in fns:
            total += (Path(d) / f).stat().st_size
    snap_rel_root = str(root / "data" / "backup" / "pre-upgrade-v0.6.0-v0.7.0-20260930_1200")
    state = {"format": "clearledger-upgrade-state/1",
             "last_plan": {"target": "v0.7.0",
                           "manifest": {"tenants_builtin": ["sales"]}},
             "in_progress": {"started_at": "2026-09-30T12:00:00", "channel": "Z", "mode": "A",
                             "from": "v0.6.0", "target": "v0.7.0",
                             "steps": ["stop", "backup", "migrate"],
                             "backup": {"at": "2026-09-30T12:01:00",
                                        "snapshot_dir": snap_rel_root,
                                        "manifest": snap_rel_root + "/backup_manifest.json"}},
             "migrate": {"intent": [{"rel": "data", "kind": "dir", "mandatory": True,
                                     "exclude": "data/upgrade", "bytes": total,
                                     "status": "done"}],
                         "built_at": "2026-09-30T12:04:00"}}
    write_text(staging / "data" / "upgrade" / "state.json", json.dumps(state))
    return root, staging, snap


class TestRollbackMidWindowBeforeSwitch(TempDirCase):
    """B1：migrate 后、switch 前的 rollback——先逆向搬回旧根再判定/恢复，
    不得把金库误记「缺失」、不得把 data/ 重造进旧根致双侧并存。"""

    def _rollback(self, root: Path):
        return upgrade.cmd_rollback(SimpleNamespace(root=root))

    def test_mid_window_case_a_reverts_then_finishes_clean(self):
        root, staging, _snap = _mid_window_zone(self.base)
        rc, _status, lines, data = self._rollback(root)
        self.assertEqual(data["case"], "0")
        self.assertTrue(any("先逆向搬回" in ln for ln in lines))
        self.assertTrue(any("情形 A" in ln for ln in lines),
                        "data 回 root 后按 root 侧实测——不得再误判")
        self.assertFalse(any("缺失" in ln for ln in lines), "金库不得被误记缺失")
        self.assertTrue((root / "data" / "warehouse" / "acme.duckdb").is_file())
        self.assertEqual((root / "data" / "warehouse" / "acme.duckdb").read_bytes(),
                         DB_BYTES)
        self.assertFalse((staging / "data").exists(),
                         "staging 侧 data 应已整体回搬——不得双侧并存")
        st = json.loads((root / "data" / "upgrade" / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(st["in_progress"])
        self.assertEqual(rc, 1)  # 夹具无 venv python：跳过门户重启（同既有用例口径）
        self.assertTrue(any("跳过门户重启" in ln for ln in lines))

    def test_mid_window_case_b_restores_bytes_at_root(self):
        root, staging, _snap = _mid_window_zone(
            self.base, staging_db_bytes=DB_BYTES + b"-tampered-in-window")
        _rc, _status, lines, data = self._rollback(root)
        self.assertEqual(data["case"], "0")
        self.assertTrue(any("情形 B" in ln for ln in lines),
                        "staging 侧金库被改写 → 回搬后偏离检出 → 情形 B")
        self.assertEqual((root / "data" / "warehouse" / "acme.duckdb").read_bytes(),
                         DB_BYTES, "被改写的金库从快照恢复（回搬后落点在 root 侧）")
        self.assertFalse((staging / "data").exists())


class TestRollbackCaseDetermination(TempDirCase):

    def _rollback(self, root: Path):
        return upgrade.cmd_rollback(SimpleNamespace(root=root))

    def test_case_a_when_fingerprints_and_schedule_clean(self):
        root, prev, _snap = _post_switch_zone(self.base)
        rc, status, lines, data = self._rollback(root)
        self.assertEqual(data["case"], "A")
        self.assertTrue(any("情形 A" in ln for ln in lines))
        # 换回后：产品根即旧根内容，持久资产随搬迁归位
        self.assertEqual((root / "VERSION").read_text(encoding="utf-8").strip(),
                         "v0.6.0")
        self.assertEqual(
            (root / "data" / "warehouse" / "acme.duckdb").read_bytes(), DB_BYTES)
        self.assertTrue((root / "instances" / "acme" / "instance.yml").is_file())
        self.assertTrue((root / ".venv" / "Scripts" / "keep.txt").is_file())
        self.assertFalse(prev.exists(), "prev 槽位应已换回产品根")
        failed = list((self.base / "zone" / "upgrade").glob("failed-*"))
        self.assertEqual(len(failed), 1)
        self.assertEqual((failed[0] / "VERSION").read_text(encoding="utf-8").strip(),
                         "v0.7.0", "新根遗骸应整体挪入 failed-*")
        # 窗口关闭：in_progress 清位
        state = json.loads(
            (root / "data" / "upgrade" / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["in_progress"])
        self.assertEqual(state["last_rollback"]["case"], "A")
        # 夹具无 .venv/Scripts/python.exe：门户重启跳过按 rc 1 记（真实环境有 venv）
        self.assertEqual(rc, 1)
        self.assertTrue(any("跳过门户重启" in ln for ln in lines))

    def test_case_b_when_duckdb_size_deviates(self):
        root, _prev, _snap = _post_switch_zone(
            self.base, live_bytes=DB_BYTES + b"-written-by-new-code")
        _rc, _status, lines, data = self._rollback(root)
        self.assertEqual(data["case"], "B")
        self.assertTrue(any("情形 B" in ln for ln in lines))
        self.assertTrue(any("偏离" in ln for ln in lines))
        # 情形 B 先恢复快照：最终产品根里的金库逐字节等于升级前
        self.assertEqual(
            (root / "data" / "warehouse" / "acme.duckdb").read_bytes(), DB_BYTES)

    def test_case_b_when_only_mtime_deviates(self):
        root, _prev, _snap = _post_switch_zone(self.base, live_mtime_shift=3600.0)
        _rc, _status, lines, data = self._rollback(root)
        self.assertEqual(data["case"], "B", "size 一致但 mtime 偏离也必须判 B")
        self.assertEqual(
            (root / "data" / "warehouse" / "acme.duckdb").read_bytes(), DB_BYTES)

    def test_case_b_when_settings_schedule_enabled(self):
        # 金库指纹完全一致，settings.json schedule_enabled=true → 一律 B（D11 补跑
        # 写库无法事后排除，步骤十保守规则）
        root, _prev, _snap = _post_switch_zone(self.base, settings_schedule=True)
        _rc, _status, lines, data = self._rollback(root)
        self.assertEqual(data["case"], "B")
        self.assertEqual(
            (root / "data" / "warehouse" / "acme.duckdb").read_bytes(), DB_BYTES)

    def test_case_b_when_smoke_record_says_schedule_enabled(self):
        # 状态机 smoke 记录（步骤九第 1 项）优先于 settings.json 重读
        root, _prev, _snap = _post_switch_zone(
            self.base, settings_schedule=False, smoke_schedule=True)
        _rc, _status, _lines, data = self._rollback(root)
        self.assertEqual(data["case"], "B")

    def test_case_b_after_finalize_ran(self):
        # Gitea 铁律：finalize 已跑必已写库 → 必然情形 B
        root, _prev, _snap = _post_switch_zone(self.base, finalize_ran=True)
        _rc, _status, _lines, data = self._rollback(root)
        self.assertEqual(data["case"], "B")

    def test_missing_live_duckdb_counts_as_deviation(self):
        root, _prev, _snap = _post_switch_zone(self.base)
        (root / "data" / "warehouse" / "acme.duckdb").unlink()
        _rc, _status, lines, data = self._rollback(root)
        self.assertEqual(data["case"], "B")
        self.assertTrue(any("缺失" in ln for ln in lines))
        self.assertEqual(
            (root / "data" / "warehouse" / "acme.duckdb").read_bytes(), DB_BYTES,
            "缺失的金库从快照恢复")


class TestRollbackCorruptSnapshotDetected(TempDirCase):
    """恢复介质损坏被检出：绝不用损坏介质覆盖现场（步骤十）。"""

    def test_tampered_snapshot_file_fails_restore_and_keeps_scene(self):
        root, _prev, snap = _post_switch_zone(
            self.base, live_bytes=DB_BYTES + b"-new-code-writes")
        # 破坏快照介质：内容动了而 manifest 的 sha256 未动
        (snap / "data" / "warehouse" / "acme.duckdb").write_bytes(b"corrupted!")
        rc, status, lines, data = self._rollback_once(root)
        self.assertEqual(rc, 1)
        self.assertEqual(data["case"], "B")
        self.assertFalse(data.get("restored", True))
        self.assertTrue(any("介质损坏" in ln for ln in lines))
        # 现场保留：在用金库未被覆盖
        self.assertEqual(
            (root / "data" / "warehouse" / "acme.duckdb").read_bytes(),
            DB_BYTES + b"-new-code-writes")

    def _rollback_once(self, root):
        return upgrade.cmd_rollback(SimpleNamespace(root=root))


class TestRollbackChannelG(TempDirCase):
    """通道 G 回滚：git reset --hard <升级前 HEAD>（情形 A 路径）。"""

    def test_case_a_resets_to_pre_upgrade_head(self):
        root = make_product_root(self.base, with_warehouse=False)
        write_text(root / ".gitignore", "data/\nlogs/\n")
        git(root, "init", "-b", "main")
        git(root, "config", "user.email", "t@example.com")
        git(root, "config", "user.name", "T")
        git(root, "add", "-A")
        git(root, "commit", "-m", "C1 pre-upgrade")
        head0 = git(root, "rev-parse", "HEAD").stdout.decode().strip()

        snap = root / "data" / "backup" / "pre-upgrade-v0.6.0-v0.7.0-20260930_1200"
        snap_db = write_bytes(snap / "data" / "warehouse" / "acme.duckdb", DB_BYTES)
        files = [{"path": "data/warehouse/acme.duckdb",
                  "sha256": sha256_file(snap_db),
                  "size": snap_db.stat().st_size,
                  "mtime": snap_db.stat().st_mtime}]
        write_text(snap / "backup_manifest.json",
                   json.dumps({"format": "clearledger-backup-manifest/1",
                               "files": files, "failed": []}))

        # 升级（sync 后形态）：VERSION 前移一次提交
        write_text(root / "VERSION", "v0.7.0\n")
        git(root, "add", "-A")
        git(root, "commit", "-m", "C2 upgrade to v0.7.0")
        # 在用金库与快照一致（情形 A 输入），定时关闭
        live_db = write_bytes(root / "data" / "warehouse" / "acme.duckdb", DB_BYTES)
        os.utime(live_db, (snap_db.stat().st_mtime,) * 2)
        write_text(root / "data" / "settings.json",
                   json.dumps({"instance": "acme", "schedule_enabled": False}))
        state = {"format": "clearledger-upgrade-state/1",
                 "last_plan": {"target": "v0.7.0",
                               "manifest": {"tenants_builtin": ["sales"]}},
                 "in_progress": {"started_at": "2026-09-30T12:00:00",
                                 "channel": "G", "mode": "A", "from": "v0.6.0",
                                 "target": "v0.7.0",
                                 "steps": ["stop", "backup", "sync"],
                                 "backup": {"at": "2026-09-30T12:01:00",
                                            "snapshot_dir": str(snap),
                                            "manifest": str(snap / "backup_manifest.json"),
                                            "git_head": head0}}}
        write_text(root / "data" / "upgrade" / "state.json", json.dumps(state))

        rc, status, lines, data = upgrade.cmd_rollback(SimpleNamespace(root=root))
        self.assertEqual(data["case"], "A")
        # 代码回到升级前 commit，工作树干净
        self.assertEqual((root / "VERSION").read_text(encoding="utf-8").strip(),
                         "v0.6.0")
        self.assertEqual(git(root, "rev-parse", "HEAD").stdout.decode().strip(),
                         head0)
        self.assertEqual(git(root, "status", "--porcelain").stdout.decode().strip(), "")
        # 未动 data/（git 不管的本地态原样保留）
        self.assertEqual(
            (root / "data" / "warehouse" / "acme.duckdb").read_bytes(), DB_BYTES)
        state2 = json.loads(
            (root / "data" / "upgrade" / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state2["in_progress"])
        # 同 TestRollbackCaseDetermination：夹具无 venv python → rc 1
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
