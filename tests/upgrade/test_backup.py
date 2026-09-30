# -*- coding: utf-8 -*-
"""ops/backup.py 测试：备份范围（build_scope）、manifest 内容（sha256/size/mtime
三字段、duckdb 指纹、mtime 保留）、命名与退出码（规格 3.3 步骤五、4 节落点 8）。"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from _util import (TempDirCase, backup, make_duckdb_file, make_product_root,
                   run_backup_main, sha256_file, write_bytes, write_text)

SIX_YML = ("instance.yml", "sources.yml", "wide.yml",
           "dimensions.yml", "metrics.yml", "dashboard.yml")


class TestBuildScope(TempDirCase):
    """范围展开：八个备份组全覆盖、缺失可选项如实记 skipped。"""

    def test_full_scope_covers_all_eight_groups(self):
        root = make_product_root(self.base, with_runs=True, with_logs=True)
        write_bytes(root / "data" / "warehouse" / "acme.duckdb.wal", b"wal-bytes")
        write_text(root / "data" / "openapi_keys.json", "{}\n")
        write_text(root / "data" / "settings.json", '{"instance": "acme"}\n')

        items, skipped = backup.build_scope(root)

        rels = {p.relative_to(root).as_posix() for p in items}
        expected = (
            {"data/warehouse/acme.duckdb", "data/warehouse/acme.duckdb.wal",
             "data/runs", "logs",
             "data/openapi_keys.json", "data/settings.json",
             "VERSION", "requirements.txt",
             "instances/acme/data",
             "instances/acme/onboarding/config_history"}
            | {f"instances/acme/{f}" for f in SIX_YML}
        )
        self.assertEqual(rels, expected)
        self.assertEqual(skipped, [])  # 本夹具该有的都有：无跳过项

    def test_missing_optional_sources_recorded_in_skipped(self):
        root = make_product_root(self.base)  # 无 runs/logs/openapi_keys/settings
        _items, skipped = backup.build_scope(root)
        skipped_paths = {s["path"] for s in skipped}
        self.assertEqual({"data/runs", "logs", "data/openapi_keys.json",
                          "data/settings.json"}, skipped_paths)
        # VERSION 与 requirements.txt 在产品根里存在，不得进 skipped
        self.assertNotIn("VERSION", skipped_paths)
        self.assertNotIn("requirements.txt", skipped_paths)
        # 每条跳过记录带原因
        for s in skipped:
            self.assertTrue(s["reason"])

    def test_instance_dir_without_instance_yml_is_not_a_tenant(self):
        root = make_product_root(self.base)
        write_text(root / "instances" / "notenant" / "metrics.yml", "x\n")
        items, skipped = backup.build_scope(root)
        rels = {p.relative_to(root).as_posix() for p in items}
        self.assertFalse(any("notenant" in r for r in rels))
        self.assertFalse(any("notenant" in s["path"] for s in skipped))

    def test_warehouse_only_takes_duckdb_and_paired_wal(self):
        root = make_product_root(self.base)
        write_text(root / "data" / "warehouse" / "readme.txt", "不是金库\n")
        write_bytes(root / "data" / "warehouse" / "other.duckdb.wal", b"w")  # 无配对库
        items, _skipped = backup.build_scope(root)
        rels = {p.relative_to(root).as_posix() for p in items}
        self.assertIn("data/warehouse/acme.duckdb", rels)
        self.assertNotIn("data/warehouse/readme.txt", rels)
        self.assertNotIn("data/warehouse/other.duckdb.wal", rels)


class TestUniqueDest(TempDirCase):
    """同名目录已存在时追加后缀——备份只增不覆盖。"""

    def test_fresh_base_unchanged(self):
        base = self.base / "data" / "backup" / "20260930_1200"
        self.assertEqual(backup._unique_dest(base), base)

    def test_existing_base_gets_suffix_2(self):
        base = self.base / "20260930_1200"
        base.mkdir()
        self.assertEqual(backup._unique_dest(base),
                         self.base / "20260930_1200-2")

    def test_suffix_2_taken_gets_suffix_3(self):
        base = self.base / "20260930_1200"
        base.mkdir()
        (self.base / "20260930_1200-2").mkdir()
        self.assertEqual(backup._unique_dest(base),
                         self.base / "20260930_1200-3")


class TestReadAppVersion(TempDirCase):
    """VERSION 读取与回退：读不到返回 None（manifest 的 app_version 允许空）。"""

    def test_reads_and_strips(self):
        write_text(self.base / "VERSION", " v0.6.0 \n")
        self.assertEqual(backup.read_app_version(self.base), "v0.6.0")

    def test_missing_returns_none(self):
        self.assertIsNone(backup.read_app_version(self.base))

    def test_empty_returns_none(self):
        write_text(self.base / "VERSION", "   \n")
        self.assertIsNone(backup.read_app_version(self.base))


class TestBackupMain(TempDirCase):
    """backup.main 全流程：快照落位、manifest 三字段指纹、退出码。"""

    def _healthy_root(self) -> Path:
        root = make_product_root(self.base, with_warehouse=False, with_runs=True)
        make_duckdb_file(root / "data" / "warehouse" / "acme.duckdb")
        write_text(root / "data" / "openapi_keys.json", "{}\n")
        write_text(root / "data" / "settings.json", '{"instance": "acme"}\n')
        return root

    def _only_snapshot_dir(self, root: Path) -> Path:
        broot = root / "data" / "backup"
        dirs = [p for p in broot.iterdir() if p.is_dir()]
        self.assertEqual(len(dirs), 1, f"应恰有一个备份目录：{dirs}")
        return dirs[0]

    def test_snapshot_manifest_contents_and_duckdb_fingerprints(self):
        root = self._healthy_root()
        rc, out, err = run_backup_main(
            ["--root", str(root), "--tag", "pre-upgrade-v0.6.0-v0.7.0"])
        self.assertEqual(rc, 0, f"备份应成功：stdout={out[-500:]} stderr={err}")

        snap = self._only_snapshot_dir(root)
        self.assertRegex(snap.name, r"^pre-upgrade-v0\.6\.0-v0\.7\.0-\d{8}_\d{4}(-\d+)?$")
        m = json.loads((snap / "backup_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(m["format"], "clearledger-backup-manifest/1")
        self.assertEqual(m["kind"], "upgrade-snapshot")
        self.assertEqual(m["tag"], "pre-upgrade-v0.6.0-v0.7.0")
        self.assertEqual(m["app_version"], "v0.6.0")
        self.assertEqual(m["root"], str(root))

        entries = {f["path"]: f for f in m["files"]}
        # 3.3 步骤五第 2 项：每条含 sha256/size/mtime 三字段
        for f in m["files"]:
            self.assertTrue({"path", "sha256", "size", "mtime"} <= set(f),
                            f"manifest 条目缺字段：{f}")
        # 金库指纹逐项核对（duckdb 的 size/mtime 字段是回滚情形判定的主证据）
        db_rel = "data/warehouse/acme.duckdb"
        self.assertIn(db_rel, entries)
        st = (root / db_rel).stat()
        e = entries[db_rel]
        self.assertGreater(e["size"], 0)
        self.assertEqual(e["size"], st.st_size)
        self.assertAlmostEqual(e["mtime"], st.st_mtime, delta=1e-6)
        self.assertEqual(e["sha256"], sha256_file(root / db_rel))
        # 其余关键资产也入清单
        self.assertEqual(entries["VERSION"]["sha256"], sha256_file(root / "VERSION"))
        self.assertIn("instances/acme/metrics.yml", entries)
        self.assertIn("data/settings.json", entries)
        # 备份件镜像落位（相对路径整树拷回的口径）且保留源 mtime
        self.assertEqual((snap / db_rel).read_bytes(), (root / db_rel).read_bytes())
        self.assertEqual((snap / db_rel).stat().st_mtime_ns, st.st_mtime_ns)
        # 失败项为空、金库只读体检全过、totals 口径自洽
        self.assertEqual(m["failed"], [])
        self.assertEqual([r["path"] for r in m["duckdb_check"]], [db_rel])
        self.assertTrue(all(r["readable"] for r in m["duckdb_check"]),
                        str(m["duckdb_check"]))
        self.assertEqual(m["totals"]["files"], len(m["files"]))
        self.assertGreater(len(m["files"]), 0)
        self.assertEqual(m["totals"]["bytes"], sum(f["size"] for f in m["files"]))
        self.assertEqual(m["totals"]["failed"], 0)

    def test_routine_backup_naming_kind_and_json_echo(self):
        root = self._healthy_root()
        rc, out, _err = run_backup_main(["--root", str(root), "--json"])
        self.assertEqual(rc, 0)
        snap = self._only_snapshot_dir(root)
        self.assertRegex(snap.name, r"^\d{8}_\d{4}(-\d+)?$")
        m = json.loads((snap / "backup_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["kind"], "routine")
        self.assertIsNone(m["tag"])
        # --json 时末行回显完整 manifest（机器可读清单）
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        echo = json.loads(last)
        self.assertEqual(echo["format"], m["format"])
        self.assertEqual(echo["files"], m["files"])

    def test_second_backup_same_tag_never_overwrites(self):
        root = self._healthy_root()
        rc1, _, _ = run_backup_main(["--root", str(root), "--tag", "t"])
        rc2, _, _ = run_backup_main(["--root", str(root), "--tag", "t"])
        self.assertEqual((rc1, rc2), (0, 0))
        dirs = [p.name for p in (root / "data" / "backup").iterdir() if p.is_dir()]
        self.assertEqual(len(dirs), 2, f"两次备份应各落一目录：{dirs}")

    def test_corrupt_duckdb_fails_loudly_not_silently(self):
        # 假金库字节：复制可成、只读体检必败——显式报错，不静默产出坏备份
        root = make_product_root(self.base)  # warehouse 里是 b"fake-quack"
        rc, out, _err = run_backup_main(["--root", str(root), "--tag", "t"])
        self.assertEqual(rc, 1)
        snap = self._only_snapshot_dir(root)
        m = json.loads((snap / "backup_manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(m["duckdb_check"][0]["readable"])
        # 复制件与指纹仍如实记录（坏库也要有清单可对账）
        db_rel = "data/warehouse/acme.duckdb"
        e = next(f for f in m["files"] if f["path"] == db_rel)
        self.assertEqual(e["size"], (root / db_rel).stat().st_size)
        self.assertEqual(e["sha256"], sha256_file(root / db_rel))

    def test_empty_warehouse_is_fatal(self):
        root = make_product_root(self.base, with_warehouse=False)
        rc, out, _err = run_backup_main(["--root", str(root)])
        self.assertEqual(rc, 1)
        self.assertIn("找不到任何账套金库", out)

    def test_invalid_tag_rejected_exit_2(self):
        root = self._healthy_root()
        for bad in ("bad/tag", "带空格", "..\\escape"):
            with self.subTest(tag=bad):
                rc, _out, err = run_backup_main(["--root", str(root), "--tag", bad])
                self.assertEqual(rc, 2)
                self.assertIn("非法字符", err)
        # 快照目录一个都没建（拒绝发生在动盘之前）
        broot = root / "data" / "backup"
        self.assertFalse(broot.exists() and any(broot.iterdir()),
                         "非法 tag 不应产出任何备份目录")


if __name__ == "__main__":
    unittest.main()
