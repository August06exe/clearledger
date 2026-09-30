# -*- coding: utf-8 -*-
"""布局与通道探测测试（3.1）：通道 G/Z（.git 有无）、模式 A/B（instances 与
data 位置）、探测不明即 fail、窗口中段视角、data/ 定位与防污染。"""
from __future__ import annotations

from _util import TempDirCase, upgrade, upgrade_common


def _mk(base, *, git=False, instances=False, data=False):
    root = base / "root"
    root.mkdir(parents=True, exist_ok=True)
    if git:
        (root / ".git").mkdir()
    if instances:
        (root / "instances").mkdir()
    if data:
        (root / "data").mkdir()
    return root


class TestDetectChannelLayout(TempDirCase):

    def test_git_with_instances_and_data_is_G_mode_A(self):
        root = _mk(self.base, git=True, instances=True, data=True)
        lay = upgrade.detect_channel_layout(root)
        self.assertTrue(lay["ok"])
        self.assertEqual(lay["channel"], "G")
        self.assertEqual(lay["mode"], "A")

    def test_no_git_with_both_is_Z_mode_A(self):
        root = _mk(self.base, instances=True, data=True)
        lay = upgrade.detect_channel_layout(root)
        self.assertTrue(lay["ok"])
        self.assertEqual((lay["channel"], lay["mode"]), ("Z", "A"))

    def test_no_git_with_neither_is_Z_mode_B(self):
        root = _mk(self.base)  # 只有裸目录
        lay = upgrade.detect_channel_layout(root)
        self.assertTrue(lay["ok"])
        self.assertEqual((lay["channel"], lay["mode"]), ("Z", "B"))

    def test_only_instances_is_unknown_and_fails(self):
        root = _mk(self.base, instances=True)
        lay = upgrade.detect_channel_layout(root)
        self.assertFalse(lay["ok"])
        self.assertEqual(lay["mode"], "unknown")
        self.assertTrue(any("探测不明" in d for d in lay["detail"]))

    def test_only_data_is_unknown_and_fails(self):
        root = _mk(self.base, data=True)
        lay = upgrade.detect_channel_layout(root)
        self.assertFalse(lay["ok"])
        self.assertEqual(lay["mode"], "unknown")

    def test_git_does_not_rescue_unknown_layout(self):
        root = _mk(self.base, git=True, instances=True)  # 有 .git 但缺 data/
        lay = upgrade.detect_channel_layout(root)
        self.assertFalse(lay["ok"])
        self.assertEqual((lay["channel"], lay["mode"]), ("G", "unknown"))


class TestWindowMode(TempDirCase):
    """停机窗中段视角：migrate 后 data 在 staging、instances 仍在旧根——视同模式 A。"""

    def test_both_in_root_is_A(self):
        root = _mk(self.base, instances=True, data=True)
        self.assertEqual(upgrade_common.window_mode(root), "A")

    def test_neither_is_B(self):
        root = _mk(self.base)
        self.assertEqual(upgrade_common.window_mode(root), "B")

    def test_data_moved_into_staging_sibling_counts_as_A(self):
        root = _mk(self.base, instances=True)
        (self.base / "upgrade" / "staging-v0.7.0" / "data").mkdir(parents=True)
        self.assertEqual(upgrade_common.window_mode(root), "A")

    def test_instances_only_without_staging_data_is_unknown(self):
        root = _mk(self.base, instances=True)
        self.assertEqual(upgrade_common.window_mode(root), "unknown")

    def test_explicit_staging_argument_honored(self):
        root = _mk(self.base, instances=True)
        staging = self.base / "elsewhere" / "staging-v0.8.0"
        staging.mkdir(parents=True)
        self.assertEqual(upgrade_common.window_mode(root, staging), "unknown")
        (staging / "data").mkdir()
        self.assertEqual(upgrade_common.window_mode(root, staging), "A")


class TestDataDir(TempDirCase):
    """data/ 定位：模式 A 根内、模式 B 平级；探测/定位绝不凭空造 data/。"""

    def test_mode_a_data_inside_root(self):
        root = _mk(self.base, instances=True, data=True)
        self.assertEqual(upgrade_common.data_dir(root), root / "data")

    def test_mode_b_data_beside_root(self):
        root = _mk(self.base)
        self.assertEqual(upgrade_common.data_dir(root), self.base / "data")

    def test_locating_never_creates_the_directory(self):
        root_a = _mk(self.base / "a", instances=True, data=True)
        root_b = _mk(self.base / "b")  # 模式 B：data 应落平级
        root_u = _mk(self.base / "c", instances=True)  # 探测不明
        upgrade_common.data_dir(root_a)
        upgrade_common.data_dir(root_b)
        upgrade_common.data_dir(root_u)
        self.assertTrue((root_a / "data").exists())
        self.assertFalse((root_b / "data").exists(), "模式 B 不得在产品根内造 data/")
        self.assertFalse((root_b.parent / "data").exists(),
                         "定位只返回路径，不得落盘平级 data/")
        self.assertFalse((root_u / "data").exists(),
                         "探测不明时定位不得落盘造目录（防污染纪律）")


if __name__ == "__main__":
    unittest.main()
