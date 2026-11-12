#!/usr/bin/env python3
"""
Seed and grow the SQLite database used by the live-ingestion example.

Create the database with a few rows::

    python examples/advanced/live-database-ingestion/seed_db.py

Then, while Potato is running, append more rows and watch them show up in the
annotation UI within one poll interval::

    python examples/advanced/live-database-ingestion/seed_db.py --add 3

Only the standard library is used, so this runs without SQLAlchemy installed.
(Potato itself needs SQLAlchemy to read the database: pip install
'potato-annotation[db]'.)
"""

import argparse
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "live.db")

SEED_MESSAGES = [
    "The new dashboard loads instantly now, this is a huge improvement.",
    "I cannot find the export button anywhere in the settings.",
    "Support got back to me within the hour, which I appreciated.",
    "Third crash this week during checkout. Getting hard to recommend.",
    "It works fine, nothing remarkable either way.",
]

LIVE_MESSAGES = [
    "Just tried the beta and the latency is noticeably better.",
    "Why does the mobile app log me out every single day?",
    "Documentation is thorough but hard to navigate.",
    "Refund was processed without any argument. Good experience.",
    "The update broke my saved filters.",
    "Neutral on the redesign so far, need more time with it.",
]


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS instances ("
        "  id TEXT PRIMARY KEY,"
        "  text TEXT NOT NULL,"
        "  created_at TEXT NOT NULL"
        ")"
    )
    return conn


def row_count(conn):
    return conn.execute("SELECT COUNT(*) FROM instances").fetchone()[0]


def insert(conn, messages, prefix):
    """Insert messages with strictly increasing timestamps."""
    added = []
    for offset, message in enumerate(messages):
        # A real application would let the database set created_at. Timestamps
        # are generated here so the ordering is deterministic in the demo.
        created_at = datetime.now(timezone.utc).isoformat()
        instance_id = f"{prefix}-{row_count(conn) + offset + 1:03d}"
        conn.execute(
            "INSERT INTO instances (id, text, created_at) VALUES (?, ?, ?)",
            (instance_id, message, created_at),
        )
        added.append(instance_id)
    conn.commit()
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--add", type=int, metavar="N",
        help="Append N new rows to an existing database instead of seeding it",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Drop all rows before seeding",
    )
    args = parser.parse_args()

    conn = connect()

    if args.reset:
        conn.execute("DELETE FROM instances")
        conn.commit()
        print("Cleared all rows.")

    if args.add:
        messages = [LIVE_MESSAGES[i % len(LIVE_MESSAGES)] for i in range(args.add)]
        added = insert(conn, messages, "live")
        print(f"Added {len(added)} row(s): {', '.join(added)}")
        print("They should appear in the annotation UI within one poll interval.")
    else:
        if row_count(conn) and not args.reset:
            print(f"Database already has {row_count(conn)} row(s) at {DB_PATH}")
            print("Use --add N to append more, or --reset to start over.")
            return
        added = insert(conn, SEED_MESSAGES, "seed")
        print(f"Seeded {len(added)} row(s) into {DB_PATH}")
        print("\nNow start Potato:")
        print("  python potato/flask_server.py start "
              "examples/advanced/live-database-ingestion/config.yaml -p 8000")

    conn.close()


if __name__ == "__main__":
    main()
