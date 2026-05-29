from __future__ import annotations

import os
import threading

import uvicorn

from aventura_bot.bot import main as run_bot
from aventura_bot.config import load_settings
from aventura_bot.db import connect


def _run_web() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("aventura_bot.web:app", host=host, port=port)


def _cleanup_bounty_board_turn() -> None:
    settings = load_settings()
    if not settings.database_path.exists():
        return
    with connect(settings.database_path) as conn:
        turn = conn.execute("SELECT * FROM turns WHERE status = 'open' ORDER BY id DESC LIMIT 1").fetchone()
        if not turn:
            return
        title = str(turn["title"] or "")
        if "Доска охотников за головами" not in title:
            return
        missions = conn.execute(
            "SELECT id, status FROM missions WHERE turn_id = ? ORDER BY id",
            (int(turn["id"]),),
        ).fetchall()
        if len(missions) <= 4:
            return
        keep_ids = {int(row["id"]) for row in missions[:4]}
        close_ids = [
            int(row["id"])
            for row in missions
            if int(row["id"]) not in keep_ids and str(row["status"]) in {"open", "ongoing"}
        ]
        if not close_ids:
            return
        conn.executemany("DELETE FROM actions WHERE mission_id = ?", [(mission_id,) for mission_id in close_ids])
        conn.executemany("DELETE FROM mission_participants WHERE mission_id = ?", [(mission_id,) for mission_id in close_ids])
        conn.executemany("UPDATE missions SET status = 'completed' WHERE id = ?", [(mission_id,) for mission_id in close_ids])
        conn.commit()


def main() -> None:
    _cleanup_bounty_board_turn()
    web_thread = threading.Thread(target=_run_web, name="tanellorn-web", daemon=True)
    web_thread.start()
    run_bot()


if __name__ == "__main__":
    main()
