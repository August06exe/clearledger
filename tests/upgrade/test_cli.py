# -*- coding: utf-8 -*-
"""ops/upgrade.py CLI 面测试：--root 解析（缺省/相对/不存在/位置约束）、
--json 状态输出结构（step/status/exit_code/root/generated_at/data）、
VERSION 读取与回退（读不到即告警，preflight 拦截）。"""
from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

from _util import (TempDirCase, make_product_root, run_upgrade_main, upgrade,
                   upgrade_common, write_text)


class TestRootResolution(TempDirCase):

    def test_nonexistent_root_exits_1(self):
        rc, _out, err, _payload = run_upgrade_main(
            ["--root", str(self.base / "nope"), "--json", "status"])
        self.assertEqual(rc, 1)
        self.assertIn("不存在", err)

    def test_relative_root_resolved_to_absolute(self):
        root = make_product_root(self.base, with_warehouse=False)
        rc, _out, _err, payload = run_upgrade_main(
            ["--root", "root", "--json", "status"], chdir=self.base)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["root"], str(root.resolve()))
        # 子命令统一拿 Path（相对根被解析成绝对路径）
        self.assertTrue(Path(payload["root"]).is_absolute())

    def test_default_root_is_script_repo_root(self):
        # 不真跑默认根（会在真实仓库 data/ 留运行日志），只钉住缺省值本身
        self.assertEqual(upgrade.build_parser().get_default("root"), str(upgrade.ROOT))
        self.assertEqual(Path(upgrade.__file__).resolve().parents[1], upgrade.ROOT)
        self.assertTrue((upgrade.ROOT / "ops" / "upgrade.py").is_file())
        self.assertTrue((upgrade.ROOT / "ops" / "backup.py").is_file())

    def test_root_after_subcommand_is_usage_error(self):
        # --root/--json 须在子命令之前（沿 6.4 命令形态）；放后面按用法错误 exit 2
        with self.assertRaises(SystemExit) as cm, \
                contextlib.redirect_stderr(io.StringIO()):
            upgrade.main(["status", "--root", str(self.base)])
        self.assertEqual(cm.exception.code, 2)


class TestJsonPayloadStructure(TempDirCase):

    def test_status_payload_structure(self):
        root = make_product_root(self.base)
        rc, _out, _err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "status"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            set(payload), {"step", "status", "exit_code", "root",
                           "generated_at", "data"})
        self.assertEqual(payload["step"], "status")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["exit_code"], 0)
        for key in ("channel", "mode", "local_version", "state",
                    "recent_logs", "plan_reports"):
            self.assertIn(key, payload["data"])
        self.assertEqual(payload["data"]["channel"], "Z")
        self.assertEqual(payload["data"]["mode"], "A")
        self.assertEqual(payload["data"]["local_version"], "v0.6.0")

    def test_failure_payload_structure(self):
        root = make_product_root(self.base)
        rc, _out, _err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "plan",
             "--manifest", str(self.base / "none.json")])
        self.assertEqual(rc, 1)
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["exit_code"], 1)
        self.assertIn("error", payload["data"])
        self.assertIn("manifest 本地文件不存在", payload["data"]["error"])

    def test_status_is_read_only(self):
        root = make_product_root(self.base, with_warehouse=False)
        before = sorted(p.relative_to(root).as_posix()
                        for p in root.rglob("*") if p.is_file())
        rc, _out, _err, _payload = run_upgrade_main(
            ["--root", str(root), "--json", "status"])
        self.assertEqual(rc, 0)
        after = sorted(p.relative_to(root).as_posix()
                       for p in root.rglob("*") if p.is_file())
        # status 探测本身只读；唯一允许的写入是 6.4 的运行日志留档
        self.assertFalse(set(before) - set(after), "既有文件被改动或删除")
        added = set(after) - set(before)
        self.assertTrue(all(p.startswith("data/upgrade/logs/") for p in added),
                        f"status 只应新增运行日志：{added}")


class TestVersionReading(TempDirCase):

    def test_read_local_version_strips(self):
        write_text(self.base / "VERSION", " v0.6.0 \n\n")
        self.assertEqual(upgrade_common.read_local_version(self.base), "v0.6.0")

    def test_read_local_version_missing_raises(self):
        with self.assertRaises(OSError):
            upgrade_common.read_local_version(self.base)

    def test_parse_semver(self):
        self.assertEqual(upgrade_common.parse_semver("v10.20.30"), (10, 20, 30))
        for bad in ("0.6.0", "v0.6", "v0.6.0.1", "", "v1.2.x", "v0.6.0-rc1"):
            with self.subTest(value=bad):
                with self.assertRaises(upgrade_common.UpgradeError):
                    upgrade_common.parse_semver(bad)

    def test_semver_cmp_ordering(self):
        cmp = upgrade_common.semver_cmp
        self.assertEqual(cmp((0, 6, 0), (0, 6, 1)), -1)
        self.assertEqual(cmp((0, 6, 1), (0, 7, 0)), -1)
        self.assertEqual(cmp((0, 10, 0), (0, 9, 0)), 1)  # 数值序
        self.assertEqual(cmp((0, 99, 99), (1, 0, 0)), -1)
        self.assertEqual(cmp((1, 2, 3), (1, 2, 3)), 0)

    def test_status_warns_when_version_unreadable(self):
        root = make_product_root(self.base, with_warehouse=False)
        (root / "VERSION").unlink()
        rc, out, _err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "status"])
        self.assertEqual(rc, 0)  # status 只读探测：告警但不误报失败
        self.assertIsNone(payload["data"]["local_version"])
        self.assertIn("VERSION 不可读", out)

    def test_status_warns_when_version_garbage(self):
        root = make_product_root(self.base, version="garbage", with_warehouse=False)
        rc, out, _err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "status"])
        self.assertEqual(rc, 0)
        self.assertIsNone(payload["data"]["local_version"])
        self.assertIn("VERSION 不可读", out)

    def test_preflight_fails_when_version_unreadable(self):
        root = make_product_root(self.base, with_warehouse=False)
        (root / "VERSION").unlink()
        rc, _out, _err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "preflight"])
        self.assertEqual(rc, 1)
        self.assertIn("本地 VERSION", payload["data"]["failed_checks"])

    def test_preflight_passes_on_healthy_fixture(self):
        root = make_product_root(self.base, with_warehouse=False)
        rc, _out, _err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "preflight"])
        self.assertEqual(rc, 0)
        self.assertEqual(payload["data"]["failed_checks"], [])
        self.assertEqual(payload["data"]["local_version"], "v0.6.0")
        # manifest 未指定时如实记 skipped（不冒充通过）
        checks = {c["check"]: c["status"] for c in payload["data"]["checks"]}
        self.assertEqual(checks["目标 manifest"], "skipped")
        self.assertEqual(checks["通道与布局探测"], "ok")


if __name__ == "__main__":
    unittest.main()
