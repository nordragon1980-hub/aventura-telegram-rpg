from __future__ import annotations

import os
import threading

import uvicorn

from aventura_bot.bot import main as run_bot


def _run_web() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("aventura_bot.web:app", host=host, port=port)


def main() -> None:
    web_thread = threading.Thread(target=_run_web, name="tanellorn-web", daemon=True)
    web_thread.start()
    run_bot()


if __name__ == "__main__":
    main()
