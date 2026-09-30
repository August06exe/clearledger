# -*- coding: utf-8 -*-
"""ops/upgrade.py sync 通过条件测试（3.3 步骤六 6B，通道 G）。

用临时 git 双仓构造 merge-base 场景：上游 origin（develop 带 tag v0.7.0、
侧支 future 带 tag v0.8.0）+ 工作仓（hro 分支带私有提交）。核心语义：
hro 两段 merge 后 HEAD 必为 merge commit、与 tag commit 永不相等——通过
条件只能用「目标 tag 是 HEAD 祖先」（git merge-base --is-ancestor），不是等值。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from _util import (TempDirCase, git, git_clone, make_product_root, upgrade,
                   write_text)


def _make_sync_pair(base: Path, *, conflict: bool = False):
    """构造 origin + 工作仓（现场节奏：克隆发生在旧版 develop，随后两侧各自前进）。

    返回 (origin, work)。形态：
      origin/develop: C1(VERSION v0.6.0, SHARED.txt=base) ← C2(VERSION v0.7.0, tag v0.7.0)
      origin/future : C3(tag v0.8.0)——不在 develop 历史内（非祖先负例）
      work: 在 C1 克隆 → hro 分支加私有提交（conflict=True 时改 SHARED.txt，
            与 origin 的 C2 同文件冲突；否则新增 private.txt）。
    因此 sync 的 hro←develop 必产生真 merge commit，HEAD 与 tag commit 永不相等。
    """
    origin = base / "origin"
    origin.mkdir(parents=True)  # git -C 需目录先存在
    git(origin, "init", "-b", "develop")
    git(origin, "config", "user.email", "t@example.com")
    git(origin, "config", "user.name", "T")
    write_text(origin / "VERSION", "v0.6.0\n")
    write_text(origin / "SHARED.txt", "base\n")
    write_text(origin / ".gitignore", "data/\nlogs/\ninstances/\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-m", "C1")

    if not conflict:
        git(origin, "checkout", "-b", "future")
        write_text(origin / "FUTURE.md", "future\n")
        git(origin, "add", "-A")
        git(origin, "commit", "-m", "C3 future")
        git(origin, "tag", "v0.8.0")
        git(origin, "checkout", "develop")

    # 工作仓先在旧版克隆、加私有提交
    work = base / "work"
    git_clone(origin, work)
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "T")
    git(work, "checkout", "-b", "hro")
    if conflict:
        write_text(work / "SHARED.txt", "private\n")
    else:
        write_text(work / "private.txt", "private\n")
    git(work, "add", "-A")
    git(work, "commit", "-m", "private commit on hro")

    # 上游 develop 随后前移出 C2
    write_text(origin / "VERSION", "v0.7.0\n")
    if conflict:
        write_text(origin / "SHARED.txt", "upstream\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-m", "C2 v0.7.0")
    git(origin, "tag", "v0.7.0")
    return origin, work


def _write_sync_state(work: Path, target: str) -> None:
    # 夹具含 backup 记录：R1 硬闸门（backup 未过任何版本移动步骤不得执行）在
    # migrate/switch/sync 前置校验，无记录会被闸门先拦，走不到本组要验的 merge/祖先路径
    state = {"format": "clearledger-upgrade-state/1",
             "last_plan": {"target": target, "manifest": {"tenants_builtin": ["sales"]}},
             "in_progress": {"started_at": "2026-09-30T12:00:00", "channel": "G",
                             "mode": "A", "from": "v0.6.0", "target": target,
                             "steps": ["stop", "backup"],
                             "backup": {"at": "2026-09-30T12:00:05",
                                        "snapshot_dir": "(fixture)", "git_head": "(fixture)"}}}
    write_text(work / "data" / "upgrade" / "state.json", json.dumps(state))


class TestSyncPassCondition(TempDirCase):

    def test_ancestor_check_passes_with_merge_commit_head(self):
        _origin, work = _make_sync_pair(self.base)
        _write_sync_state(work, "v0.7.0")

        rc, status, lines, data = upgrade.cmd_sync(SimpleNamespace(root=work))
        self.assertEqual((rc, status), (0, "ok"))
        self.assertTrue(any("祖先校验" in ln and "✅" in ln for ln in lines))

        head = git(work, "rev-parse", "HEAD").stdout.decode().strip()
        tag_commit = git(work, "rev-parse", "v0.7.0^{commit}").stdout.decode().strip()
        self.assertEqual(data["head"], head)
        self.assertEqual(data["target"], "v0.7.0")
        # hro 带私有提交：HEAD 是两段 merge 产生的新 commit，与 tag 永不相等——
        # 等值校验必假，这就是通过条件用祖先包含的机理
        self.assertNotEqual(head, tag_commit)
        self.assertEqual(
            git(work, "merge-base", "--is-ancestor", tag_commit, "HEAD").returncode, 0)
        # 停在工作分支，版本内容随 merge 前移
        self.assertEqual(
            git(work, "rev-parse", "--abbrev-ref", "HEAD").stdout.decode().strip(),
            "hro")
        self.assertEqual((work / "VERSION").read_text(encoding="utf-8").strip(),
                         "v0.7.0")
        # 工作树干净（data/ 已被 .gitignore 覆盖），无未解决冲突
        self.assertEqual(git(work, "status", "--porcelain").stdout.decode().strip(), "")
        self.assertEqual(git(work, "ls-files", "-u").stdout.decode().strip(), "")
        # 状态机记账
        state = json.loads(
            (work / "data" / "upgrade" / "state.json").read_text(encoding="utf-8"))
        self.assertIn("sync", state["in_progress"]["steps"])
        self.assertEqual(state["in_progress"]["sync"]["head"], head)

    def test_tag_not_ancestor_of_head_fails(self):
        # v0.8.0 在 origin 的侧支上，develop/hro 都没并入 → 不是 HEAD 祖先
        _origin, work = _make_sync_pair(self.base)
        _write_sync_state(work, "v0.8.0")
        with self.assertRaises(upgrade.UpgradeError) as cm:
            upgrade.cmd_sync(SimpleNamespace(root=work))
        self.assertIn("不是 HEAD", str(cm.exception))
        self.assertIn("v0.8.0", str(cm.exception))

    def test_merge_conflict_kept_for_manual_reconciliation(self):
        # 冲突时不自动 abort：现场保留（ls-files -u 非空）+ 输出登记簿对账指引
        _origin, work = _make_sync_pair(self.base, conflict=True)
        _write_sync_state(work, "v0.7.0")
        with self.assertRaises(upgrade.UpgradeError) as cm:
            upgrade.cmd_sync(SimpleNamespace(root=work))
        self.assertIn("merge develop", str(cm.exception))
        lines = cm.exception.lines or []
        self.assertTrue(any("登记簿" in ln for ln in lines),
                        f"应输出对账指引：{lines}")
        self.assertTrue(any("冲突文件" in ln for ln in lines))
        # 现场保留：冲突未解决、未自动 abort 回升级前
        self.assertNotEqual(git(work, "ls-files", "-u").stdout.decode().strip(), "")
        self.assertEqual(
            git(work, "rev-parse", "--abbrev-ref", "HEAD").stdout.decode().strip(),
            "hro")

    def test_sync_requires_open_window(self):
        _origin, work = _make_sync_pair(self.base)  # 未写 state.json
        with self.assertRaises(upgrade.UpgradeError) as cm:
            upgrade.cmd_sync(SimpleNamespace(root=work))
        self.assertIn("无 in_progress", str(cm.exception))

    def test_channel_z_rejected(self):
        root = make_product_root(self.base)  # 无 .git
        with self.assertRaises(upgrade.UpgradeError) as cm:
            upgrade.cmd_sync(SimpleNamespace(root=root))
        self.assertIn("通道 Z 无 sync", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
