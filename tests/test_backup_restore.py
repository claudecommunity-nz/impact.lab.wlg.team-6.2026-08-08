"""Backup and restore are exercised, not assumed: create a real store,
back it up with the sqlite backup API, restore into a scratch directory
and verify integrity and row counts survive the round trip.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "kitea_backup", REPO / "scripts" / "kitea_backup.py")
kitea_backup = importlib.util.module_from_spec(spec)
sys.modules["kitea_backup"] = kitea_backup
spec.loader.exec_module(kitea_backup)


class TestBackupRestore(unittest.TestCase):
    def test_round_trip_preserves_reports_and_uploads(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            out = Path(tmp) / "backups"
            (data / "uploads").mkdir(parents=True)
            (data / "uploads" / "photo1.jpg").write_bytes(b"\xff\xd8\xfffake")

            # a real store with real rows, via the actual store module
            import kitea.store as store
            store.init(data / "kitea.db")
            made = [store.create_report(category="flooding",
                                        description=f"row {i}")
                    for i in range(3)]
            store.add_status(made[0]["ref"], "reviewing", actor="test")

            archive = kitea_backup.backup(data, out)
            self.assertTrue(archive.exists())

            result = kitea_backup.verify(archive)
            self.assertEqual(result["integrity"], "ok")
            self.assertEqual(result["reports"], 3)
            # 3 auto-received events + 1 manual
            self.assertEqual(result["status_events"], 4)
            self.assertEqual(result["uploads"], 1)

    def test_verify_fails_on_corrupt_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "kitea-corrupt.tar.gz"
            bad.write_bytes(b"this is not a tar file")
            import tarfile
            with self.assertRaises(tarfile.ReadError):
                kitea_backup.verify(bad)


if __name__ == "__main__":
    unittest.main()
