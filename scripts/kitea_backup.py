"""Backup and restore-verify for a Kitea data directory. Stdlib only.

Backup produces a tar.gz containing a CONSISTENT SQLite snapshot (taken
with the sqlite3 backup API, safe against concurrent writers in WAL mode)
plus the photo uploads. Restore-verify actually restores the archive into
a scratch directory, opens the database, runs an integrity check and
counts rows: an untested backup is not a backup.

    python3 scripts/kitea_backup.py backup  --data data --out /var/backups/kitea
    python3 scripts/kitea_backup.py verify  --archive <file.tar.gz>
    python3 scripts/kitea_backup.py latest  --out /var/backups/kitea

Encryption is applied by the caller (the on-box timer pipes through
openssl with a key in /root); CI exercises the unencrypted path.
Retention: backup keeps the newest 14 archives in --out.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

KEEP = 14


def backup(data_dir: Path, out_dir: Path) -> Path:
    db_path = data_dir / "kitea.db"
    if not db_path.exists():
        raise SystemExit(f"no database at {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archive = out_dir / f"kitea-{stamp}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "kitea.db"
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)          # consistent snapshot, WAL-safe
        src.close()
        dst.close()
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(snap, arcname="kitea.db")
            uploads = data_dir / "uploads"
            if uploads.is_dir():
                tar.add(uploads, arcname="uploads")

    archives = sorted(out_dir.glob("kitea-*.tar.gz*"))
    for old in archives[:-KEEP]:
        old.unlink()
    return archive


def verify(archive: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(archive, "r:gz") as tar:
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:
                # Python < 3.11.4 has no filter=; validate members manually
                for m in tar.getmembers():
                    name = m.name.replace("\\", "/")
                    if name.startswith("/") or ".." in name or \
                            not name.startswith(("kitea.db", "uploads")):
                        raise SystemExit(
                            f"unexpected archive member: {m.name}") from None
                tar.extractall(tmp)  # noqa: S202 (members validated above)
        db = sqlite3.connect(Path(tmp) / "kitea.db")
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        reports = db.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        events = db.execute("SELECT COUNT(*) FROM status_events").fetchone()[0]
        db.close()
        uploads = list((Path(tmp) / "uploads").glob("*")) if (Path(tmp) / "uploads").is_dir() else []
    result = {"integrity": integrity, "reports": reports,
              "status_events": events, "uploads": len(uploads)}
    if integrity != "ok":
        raise SystemExit(f"RESTORE FAILED integrity={integrity}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["backup", "verify", "latest"])
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="/var/backups/kitea")
    ap.add_argument("--archive")
    args = ap.parse_args()

    if args.action == "backup":
        archive = backup(Path(args.data), Path(args.out))
        print(archive)
    elif args.action == "latest":
        archives = sorted(Path(args.out).glob("kitea-*.tar.gz"))
        if not archives:
            raise SystemExit("no archives")
        print(archives[-1])
    else:
        target = Path(args.archive) if args.archive else None
        if target is None:
            raise SystemExit("verify needs --archive")
        result = verify(target)
        print(f"RESTORE OK {result}")


if __name__ == "__main__":
    sys.exit(main())
