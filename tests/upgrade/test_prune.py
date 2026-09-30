# -*- coding: utf-8 -*-
"""ops/upgrade.py prune 保留策略测试（3.3 步骤十一）：

prev 目录严格匹配 prev-vX.Y.Z 才删、按语义化版本保留最近两代（数值序非字典序）；
升级快照（data/backup/pre-upgrade-*）只列不删、永不自动删除；prune 关闭回滚
窗口（清 in_progress）——通道 Z 与 G 都关窗，G 跳过 prev 收敛（B3）。"""
from __future__ import annotations

import json
from types import SimpleNamespace

from _util import TempDirCase, make_product_root, upgrade, write_text

PREVS = ("v0.5.0", "v0.9.0", "v0.10.0", "v0.11.0")
SNAP_DATES = ("20260101_0000", "20260201_0000", "20260301_0000",
              "20260401_0000", "20260501_0000")


def _prune_fixture(base, *, with_state=True):
    root = make_product_root(base, with_warehouse=False)  # 无 .git → 通道 Z
    ups = base / "upgrade"
    for v in PREVS:
        write_text(ups / f"prev-{v}" / "keep.txt", f"prev {v}\n")
    # 干扰项：不匹配严格模式的一律不动
    write_text(ups / "prev-v0.6" / "x.txt", "残缺版本号\n")       # 缺一段
    write_text(ups / "prev-old" / "x.txt", "非语义化名\n")
    write_text(ups / "staging-v0.7.0" / "VERSION", "v0.7.0\n")     # 非 prev
    broot = root / "data" / "backup"
    for d in SNAP_DATES:
        write_text(broot / f"pre-upgrade-v0.5.0-v0.6.0-{d}" / "acme.duckdb", "x")
    write_text(broot / "20260101_0000" / "acme.duckdb", "例行备份，非快照\n")
    if with_state:
        state = {"format": "clearledger-upgrade-state/1",
                 "last_plan": {"target": "v0.7.0", "manifest": {}},
                 "in_progress": {"started_at": "t", "channel": "Z", "mode": "A",
                                 "from": "v0.6.0", "target": "v0.7.0",
                                 "steps": ["stop"]}}
        write_text(root / "data" / "upgrade" / "state.json", json.dumps(state))
    return root, ups, broot


class TestPrune(TempDirCase):

    def _prune(self, root):
        return upgrade.cmd_prune(SimpleNamespace(root=root))

    def test_keeps_two_newest_prevs_deletes_older_numerically(self):
        root, ups, _broot = _prune_fixture(self.base)
        rc, status, lines, data = self._prune(root)
        self.assertEqual((rc, status), (0, "ok"))
        # 语义化数值序：v0.11 > v0.10 > v0.9 > v0.5（字典序会把 0.9 排到 0.10 前）
        self.assertEqual(data["prev_kept"], ["prev-v0.11.0", "prev-v0.10.0"])
        self.assertEqual(data["prev_removed"], ["prev-v0.9.0", "prev-v0.5.0"])
        for v in ("v0.11.0", "v0.10.0"):
            self.assertTrue((ups / f"prev-{v}").is_dir(), f"prev-{v} 应保留")
        for v in ("v0.9.0", "v0.5.0"):
            self.assertFalse((ups / f"prev-{v}").exists(), f"prev-{v} 应删除")
        # 严格匹配之外的一律不动
        self.assertTrue((ups / "prev-v0.6").is_dir())
        self.assertTrue((ups / "prev-old").is_dir())
        self.assertTrue((ups / "staging-v0.7.0").is_dir())

    def test_snapshots_listed_but_never_deleted(self):
        root, _ups, broot = _prune_fixture(self.base)
        rc, _status, _lines, data = self._prune(root)
        self.assertEqual(rc, 0)
        within = {f"pre-upgrade-v0.5.0-v0.6.0-{d}" for d in SNAP_DATES[-3:]}
        older = {f"pre-upgrade-v0.5.0-v0.6.0-{d}" for d in SNAP_DATES[:2]}
        self.assertEqual(set(data["snapshots_within_3"]), within)
        self.assertEqual(set(data["snapshots_older"]), older)
        # 五份快照全部还在——prune 永不删快照（人确认后手删）
        for d in SNAP_DATES:
            self.assertTrue((broot / f"pre-upgrade-v0.5.0-v0.6.0-{d}").is_dir())
        # 例行备份目录不进快照清单
        self.assertTrue((broot / "20260101_0000").is_dir())

    def test_prune_closes_rollback_window(self):
        root, _ups, _broot = _prune_fixture(self.base, with_state=True)
        rc, status, lines, data = self._prune(root)
        self.assertEqual(rc, 0)
        self.assertTrue(any("回滚窗口关闭" in ln for ln in lines))
        state = json.loads(
            (root / "data" / "upgrade" / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["in_progress"])
        self.assertEqual(state["window_closed_by"]["step"], "prune")

    def test_no_prevs_is_ok(self):
        root = make_product_root(self.base, with_warehouse=False)
        rc, status, lines, data = self._prune(root)
        self.assertEqual((rc, status), (0, "ok"))
        self.assertEqual(data["prev_removed"], [])

    def test_channel_g_prune_closes_window_without_prev_ops(self):
        """B3：通道 G 放开 prune——跳过 prev 收敛、保留快照列示、执行关窗
        （不再逼 R-14 用裸 python -c 清位，目标 1「每步一条命令」）。"""
        root = make_product_root(self.base, with_git=True)  # .git → 通道 G
        broot = root / "data" / "backup"
        write_text(broot / "pre-upgrade-v0.6.0-v0.7.0-20260101_0000" / "acme.duckdb", "x")
        state = {"format": "clearledger-upgrade-state/1",
                 "last_plan": {"target": "v0.7.0", "manifest": {}},
                 "in_progress": {"started_at": "t", "channel": "G", "mode": "A",
                                 "from": "v0.6.0", "target": "v0.7.0",
                                 "steps": ["stop", "backup", "sync"]}}
        write_text(root / "data" / "upgrade" / "state.json", json.dumps(state))
        rc, status, lines, data = self._prune(root)
        self.assertEqual((rc, status), (0, "ok"))
        self.assertTrue(any("跳过 prev 收敛" in ln for ln in lines))
        self.assertEqual(data["prev_kept"] + data["prev_removed"], [])
        self.assertEqual(data["snapshots_within_3"],
                         ["pre-upgrade-v0.6.0-v0.7.0-20260101_0000"])
        self.assertTrue((broot / "pre-upgrade-v0.6.0-v0.7.0-20260101_0000").is_dir())
        st = json.loads((root / "data" / "upgrade" / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(st["in_progress"], "通道 G 的窗口同样由 prune 关闭")
        self.assertEqual(st["window_closed_by"]["step"], "prune")


if __name__ == "__main__":
    unittest.main()
