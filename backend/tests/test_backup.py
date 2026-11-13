import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.backup import backup_sqlite_database


class SqliteBackupTests(unittest.TestCase):
    def test_creates_integrity_checked_backup_and_reuses_daily_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "nexsafe.db"
            backup_directory = root / "backups"
            with closing(sqlite3.connect(source_path)) as connection:
                connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
                connection.execute("INSERT INTO records VALUES ('persisted')")
                connection.commit()

            backup_time = datetime(2026, 11, 13, tzinfo=timezone.utc)
            database_url = f"sqlite+aiosqlite:///{source_path.as_posix()}"
            backup_path = backup_sqlite_database(
                database_url,
                backup_directory,
                backup_time,
            )

            self.assertIsNotNone(backup_path)
            with closing(sqlite3.connect(backup_path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT value FROM records").fetchone(),
                    ("persisted",),
                )
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone(),
                    ("ok",),
                )

            repeated_backup = backup_sqlite_database(
                database_url,
                backup_directory,
                backup_time,
            )
            self.assertEqual(repeated_backup, backup_path)
            self.assertEqual(len(list(backup_directory.iterdir())), 1)

    def test_missing_database_does_not_create_empty_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_path = root / "missing.db"
            backup_directory = root / "backups"

            backup = backup_sqlite_database(
                f"sqlite+aiosqlite:///{missing_path.as_posix()}",
                backup_directory,
            )

            self.assertIsNone(backup)
            self.assertFalse(backup_directory.exists())

    def test_non_sqlite_database_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "require a SQLite"):
                backup_sqlite_database(
                    "postgresql+asyncpg://localhost/nexsafe",
                    Path(directory) / "backups",
                )


if __name__ == "__main__":
    unittest.main()
