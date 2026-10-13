"""
Backup + usage report for trAIned.

Copies every table from the live database (PostgreSQL via DATABASE_URL, or the
local SQLite file) into CSV files and builds a usage report with real numbers.
Read-only: nothing in the database is changed.

Usage (from the project root):
    python scripts/backup.py                            # DATABASE_URL from .env / environment
    python scripts/backup.py --db "postgresql://..."    # or pass the URL directly

Result:
    backups/2026-10-08_1530/
        users.csv, profile.csv, workout_log.csv, ...    (password hashes and session tokens are never exported)
        stats.json   - all numbers in machine-readable form
        report.html  - the same numbers as a page with charts
    backups/2026-10-08_1530.zip

The backups/ folder contains personal data. It is git-ignored: never commit it.
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from backend.stats import build_backup  # noqa: E402


class ReadOnlyPg:
    """psycopg2 connection that behaves like sqlite3 for the stats code, in read-only mode."""
    def __init__(self, dsn):
        import psycopg2
        import psycopg2.extras
        self._conn = psycopg2.connect(dsn)
        self._conn.set_session(readonly=True, autocommit=True)
        self._dict_cursor = psycopg2.extras.RealDictCursor

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=self._dict_cursor)
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def rollback(self):
        pass  # autocommit: a failed query doesn't poison the session

    def close(self):
        self._conn.close()


def connect(db_url):
    if db_url.startswith("postgres"):
        return ReadOnlyPg(db_url), "PostgreSQL"
    path = os.path.join(ROOT, "trained.db")
    if not os.path.exists(path):
        sys.exit('No DATABASE_URL and no local trained.db. Run with --db "postgresql://..."')
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn, "SQLite (trained.db)"


def main():
    ap = argparse.ArgumentParser(description="Backup trAIned data and build a usage report")
    ap.add_argument("--db", default=os.getenv("DATABASE_URL", ""), help="database URL (default: DATABASE_URL)")
    ap.add_argument("--out", default=os.path.join(ROOT, "backups"), help="output folder")
    args = ap.parse_args()

    conn, kind = connect(args.db.strip())
    files, stats = build_backup(conn)
    conn.close()

    out_dir = os.path.join(args.out, datetime.now().strftime("%Y-%m-%d_%H%M"))
    os.makedirs(out_dir, exist_ok=True)
    for name, data in files.items():
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
    archive = shutil.make_archive(out_dir, "zip", out_dir)

    u, t = stats["users"], stats["training"]
    print(f"Source: {kind}")
    for table, n in stats["row_counts"].items():
        print(f"  {table:<14} {n:>7} rows")
    print("\nSummary")
    print(f"  users registered      {u['registered']}")
    print(f"  active (1+ entry)     {u['active_ever']}")
    print(f"  returned on 2+ days   {u['returned_2plus_days']}")
    print(f"  workout sessions      {t['workout_sessions']}")
    print(f"  sets logged           {t['sets_logged']}")
    print(f"  meals logged          {stats['nutrition']['meals_logged']}")
    print(f"\nReport:  {os.path.join(out_dir, 'report.html')}")
    print(f"Archive: {archive}")


if __name__ == "__main__":
    main()
