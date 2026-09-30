# -*- coding: utf-8 -*-
"""ops/upgrade.py manifest 解析（含坏输入）与 plan 子命令测试。

规格：6.2 upgrade-manifest.json 十四字段、3.3 步骤一（版本方向 / below_min
exit 2 / 报告落盘 / last_plan 状态机传递）。"""
from __future__ import annotations

import json
import unittest

from _util import (TempDirCase, full_manifest, make_product_root,
                   run_upgrade_main, upgrade, write_text)

UPGRADE_MD = """# 升级须知（夹具）
## v0.6.1
- 演示：小版本条目
## v0.7.0
- 演示：目标版条目
## v0.8.0
- 演示：未来版条目（不应入选）
"""


class TestValidateManifest(unittest.TestCase):
    """6.2 十四字段的存在性+类型校验。"""

    def test_valid_full_manifest_has_no_issues(self):
        self.assertEqual(upgrade.validate_manifest(full_manifest()), [])

    def test_every_missing_field_reported(self):
        issues = upgrade.validate_manifest({})
        self.assertEqual(len(issues), len(upgrade.MANIFEST_FIELDS))
        self.assertTrue(all(i.startswith("缺字段") for i in issues))

    def test_missing_zip_sha256_reported_by_name(self):
        m = full_manifest()
        del m["zip_sha256"]
        issues = upgrade.validate_manifest(m)
        self.assertEqual(issues, ["缺字段 zip_sha256"])

    def test_version_without_v_prefix_rejected(self):
        issues = upgrade.validate_manifest(full_manifest(version="0.7.0"))
        self.assertEqual([i for i in issues if "version" in i],
                         ["字段 version 类型不符（期望 semver）"])

    def test_zip_sha256_must_be_64_lowercase_hex(self):
        for bad in ("XYZ" * 21 + "x", "a" * 63, "a" * 64 + "a", 123):
            with self.subTest(zip_sha256=bad):
                issues = upgrade.validate_manifest(full_manifest(zip_sha256=bad))
                self.assertIn("字段 zip_sha256 类型不符（期望 sha256）", issues)

    def test_bool_rejected_for_int_field(self):
        # bool 是 int 子类——contract_version=True 必须被识别为类型不符
        issues = upgrade.validate_manifest(full_manifest(contract_version=True))
        self.assertIn("字段 contract_version 类型不符（期望 int）", issues)

    def test_string_rejected_for_bool_field(self):
        issues = upgrade.validate_manifest(full_manifest(launcher_rebuilt="false"))
        self.assertIn("字段 launcher_rebuilt 类型不符（期望 bool）", issues)

    def test_tenants_builtin_must_be_list_of_str(self):
        for bad in (["sales", 3], "sales", ["ok", None]):
            with self.subTest(tenants_builtin=bad):
                issues = upgrade.validate_manifest(full_manifest(tenants_builtin=bad))
                self.assertIn("字段 tenants_builtin 类型不符（期望 list_str）", issues)

    def test_config_schema_version_must_be_dict(self):
        issues = upgrade.validate_manifest(full_manifest(config_schema_version=1))
        self.assertIn("字段 config_schema_version 类型不符（期望 dict）", issues)

    def test_top_level_must_be_json_object(self):
        self.assertEqual(upgrade.validate_manifest(["not", "a", "dict"]),
                         ["manifest 顶层不是 JSON 对象"])


class TestLoadManifest(TempDirCase):
    """manifest 两取法之本地路径（URL 分支出网，不在单测里跑）。"""

    def test_local_file_loaded_with_file_source(self):
        mpath = write_text(self.base / "manifest.json",
                           json.dumps(full_manifest(), ensure_ascii=False))
        m, source = upgrade.load_manifest(None, str(mpath))
        self.assertEqual(m["version"], "v0.7.0")
        self.assertEqual(source, f"file:{mpath}")

    def test_missing_local_file_raises_upgrade_error(self):
        with self.assertRaises(upgrade.UpgradeError) as cm:
            upgrade.load_manifest(None, str(self.base / "none.json"))
        self.assertIn("不存在", str(cm.exception))

    def test_bad_json_content_raises(self):
        mpath = write_text(self.base / "manifest.json", "这不是 JSON")
        with self.assertRaises(ValueError):
            upgrade.load_manifest(None, str(mpath))


class TestPlan(TempDirCase):
    """plan 子命令（--manifest 走本地路径，全程不出网）。"""

    def _fixture(self, local_version: str = "v0.6.0"):
        root = make_product_root(self.base, version=local_version)
        write_text(root / "UPGRADE.md", UPGRADE_MD)
        mpath = write_text(self.base / "manifest.json",
                           json.dumps(full_manifest(), ensure_ascii=False))
        return root, mpath

    def test_plan_ok_writes_report_and_last_plan(self):
        root, mpath = self._fixture()
        rc, out, err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "plan", "--manifest", str(mpath)])
        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["exit_code"], 0)

        report = json.loads(
            __import__("pathlib").Path(payload["data"]["report_path"])
            .read_text(encoding="utf-8"))
        self.assertEqual(report["format"], "clearledger-upgrade-plan-report/1")
        self.assertEqual(report["channel"], "Z")
        self.assertEqual(report["mode"], "A")
        vc = report["version_check"]
        self.assertEqual((vc["local"], vc["target"]), ("v0.6.0", "v0.7.0"))
        self.assertEqual(vc["direction"], "升级")
        self.assertFalse(vc["below_min_upgradable_from"])
        # UPGRADE.md 只纳入 (本地, 目标] 的节
        self.assertEqual(report["upgrade_md"]["sections_used"],
                         ["v0.6.1", "v0.7.0"])
        # 分诊字段来自 manifest
        self.assertEqual(report["triage"]["sentinel_reports"], ["region_month"])
        self.assertFalse(report["triage"]["canary_required"])
        self.assertTrue(report["triage"]["human_approval_required"])
        # last_plan 落状态机：stop/backup 命令面无参，目标只能经状态机传递
        state = json.loads(
            (root / "data" / "upgrade" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["last_plan"]["target"], "v0.7.0")
        self.assertEqual(state["last_plan"]["manifest"]["version"], "v0.7.0")

    def test_plan_rejects_non_upgrade_direction(self):
        root, _mpath = self._fixture()
        mpath = write_text(self.base / "same.json",
                           json.dumps(full_manifest(version="v0.6.0"), ensure_ascii=False))
        rc, out, err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "plan", "--manifest", str(mpath)])
        self.assertEqual(rc, 1)
        self.assertEqual(payload["status"], "fail")
        self.assertIn("版本方向", payload["data"]["error"])
        self.assertIn("目标必须高于本地", payload["data"]["error"])

    def test_plan_below_min_upgradable_exits_2_with_blocked_report(self):
        root, _mpath = self._fixture(local_version="v0.5.0")
        mpath = write_text(self.base / "gap.json",
                           json.dumps(full_manifest(version="v0.7.0",
                                                    min_upgradable_from="v0.6.0"),
                                      ensure_ascii=False))
        rc, out, err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "plan", "--manifest", str(mpath)])
        self.assertEqual(rc, 2)
        self.assertEqual(payload["exit_code"], 2)
        report = json.loads(
            __import__("pathlib").Path(payload["data"]["report_path"])
            .read_text(encoding="utf-8"))
        self.assertIn("低于 min_upgradable_from", report["blocked"])
        self.assertTrue(report["version_check"]["below_min_upgradable_from"])
        # 中间版本清单字段在（能否枚举取决于网络，不在此断言内容）
        self.assertIn("intermediate_versions", report)

    def test_plan_bad_manifest_json_wrapped_as_upgrade_error(self):
        root, _mpath = self._fixture()
        mpath = write_text(self.base / "broken.json", "not-json{{{")
        rc, out, err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "plan", "--manifest", str(mpath)])
        self.assertEqual(rc, 1)
        self.assertIn("manifest 解析失败", payload["data"]["error"])

    def test_plan_field_validation_failure_names_fields(self):
        root, _mpath = self._fixture()
        m = full_manifest()
        m["zip_sha256"] = "short"
        mpath = write_text(self.base / "bad_fields.json",
                           json.dumps(m, ensure_ascii=False))
        rc, out, err, payload = run_upgrade_main(
            ["--root", str(root), "--json", "plan", "--manifest", str(mpath)])
        self.assertEqual(rc, 1)
        self.assertIn("zip_sha256", payload["data"]["error"])
        self.assertIn("6.2 字段校验", payload["data"]["error"])


if __name__ == "__main__":
    unittest.main()
