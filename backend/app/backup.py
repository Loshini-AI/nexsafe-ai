import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url


def _is_valid_backup(path: Path) -> bool:
    try:
        with closing(sqlite3.connect(path)) as connection:
            return connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    except sqlite3.Error:
        return False


def backup_sqlite_database(
    database_url: str,
    backup_directory: Path,
    backup_time: datetime | None = None,
) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("Automatic local backups require a SQLite database.")
    if not url.database or url.database == ":memory:":
        raise ValueError("A file-backed SQLite database is required for backups.")

    source_path = Path(url.database).resolve()
    if not source_path.is_file():
        return None

    backup_directory.mkdir(parents=True, exist_ok=True)
    backup_date = (backup_time or datetime.now(timezone.utc)).strftime("%Y%m%d")
    target_path = backup_directory / f"nexsafe-{backup_date}.db"
    if target_path.exists():
        if _is_valid_backup(target_path):
            return target_path
        suffix = (backup_time or datetime.now(timezone.utc)).strftime("%H%M%S%f")
        target_path = backup_directory / f"nexsafe-{backup_date}-{suffix}.db"

    try:
        with closing(sqlite3.connect(source_path, timeout=30)) as source:
            with closing(sqlite3.connect(target_path, timeout=30)) as target:
                source.backup(target)
                result = target.execute("PRAGMA integrity_check").fetchone()
                if result != ("ok",):
                    raise sqlite3.DatabaseError(
                        f"SQLite backup integrity check failed: {result!r}"
                    )
    except Exception:
        target_path.unlink(missing_ok=True)
        raise

    return target_path


def main() -> None:
    from app.config import project_root, settings

    backup_path = backup_sqlite_database(
        settings.database_url,
        project_root / "data" / "backups",
    )
    if backup_path is None:
        print("No existing file-backed SQLite database to back up.")
        return
    print(f"SQLite backup verified: {backup_path}")


if __name__ == "__main__":
    main()
