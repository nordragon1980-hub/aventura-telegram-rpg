#!/usr/bin/env python3
"""Close unwanted missions on the current open turn.

Use this for GM maintenance when old carried board missions should be hidden
from the current mission board. By default it keeps the first four missions of
the current open turn, which matches the freshly uploaded bounty-hunter turn.

Examples:
  python scripts/cleanup_open_turn_missions.py /data/aventura.sqlite --dry-run
  python scripts/cleanup_open_turn_missions.py /data/aventura.sqlite --keep 50,51,52,53
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def parse_keep(raw: str) -> set[int]:
    values: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk:
            values.add(int(chunk))
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--keep", default="", help="Comma-separated mission ids to keep open.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_path = args.database.expanduser().resolve()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    turn = conn.execute("SELECT * FROM turns WHERE status = 'open' ORDER BY id DESC LIMIT 1").fetchone()
    if not turn:
        print("No open turn found.")
        return 1

    rows = conn.execute(
        "SELECT id, title, status FROM missions WHERE turn_id = ? ORDER BY id",
        (int(turn["id"]),),
    ).fetchall()
    if not rows:
        print(f"Open turn #{turn['id']} has no missions.")
        return 1

    keep_ids = parse_keep(args.keep) if args.keep else {int(row["id"]) for row in rows[:4]}
    close_ids = [int(row["id"]) for row in rows if int(row["id"]) not in keep_ids and row["status"] in {"open", "ongoing"}]

    print(f"Open turn #{turn['id']}: {turn['title']}")
    print("Keeping:")
    for row in rows:
        marker = "KEEP" if int(row["id"]) in keep_ids else "close" if int(row["id"]) in close_ids else "skip"
        print(f"  {marker:5} #{row['id']} [{row['status']}] {row['title']}")

    if args.dry_run:
        print("Dry run only; no changes written.")
        return 0

    if close_ids:
        conn.executemany("UPDATE missions SET status = 'closed' WHERE id = ?", [(mission_id,) for mission_id in close_ids])
        conn.commit()
    print(f"Closed {len(close_ids)} missions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
