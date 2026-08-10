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


class TestRetention(unittest.TestCase):
    def test_privacy_schedule_enforced(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            import kitea.store as store
            store.init(Path(tmp) / "kitea.db")
            fresh = store.create_report(category="other", description="fresh row",
                                        contact="021 111")
            old_resolved = store.create_report(category="other", description="old resolved",
                                               contact="021 222", photo="old.jpg")
            store.add_status(old_resolved["ref"], "resolved", actor="test")
            (Path(tmp) / "old.jpg").write_bytes(b"x")

            db = sqlite3.connect(Path(tmp) / "kitea.db")
            with db:
                db.execute("UPDATE status_events SET created_at='2025-01-01T00:00:00+00:00'"
                           " WHERE ref=?", (old_resolved["ref"],))
                db.execute("UPDATE reports SET created_at='2024-01-01T00:00:00+00:00'"
                           " WHERE ref=?", (old_resolved["ref"],))
            db.close()

            removed = store.apply_retention(uploads_dir=Path(tmp))
            self.assertEqual(removed["contacts"], 1)
            self.assertEqual(removed["photos"], 1)
            self.assertFalse((Path(tmp) / "old.jpg").exists())

            kept = store.get_report(fresh["ref"], private=True)
            self.assertEqual(kept["contact"], "021 111")   # fresh survives
            gone = store.get_report(old_resolved["ref"], private=True)
            self.assertIsNone(gone["contact"])
            self.assertIsNone(gone["photo"])
            # the report row itself survives, anonymised, for planning
            self.assertEqual(gone["description"], "old resolved")


if __name__ == "__main__":
    unittest.main()
