from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qsl

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aventura_bot.config import Settings, load_settings
from aventura_bot.services.game import build_tanellorn_map_state


STATIC_ROOT = Path(__file__).with_name("static")
TANELLORN_PAGE = STATIC_ROOT / "tanellorn" / "index.html"
TELEGRAM_AUTH_MAX_AGE_SECONDS = 24 * 60 * 60


def _telegram_user_id(init_data: str, bot_token: str) -> int | None:
    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", "")
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        return None
    try:
        auth_date = int(values.get("auth_date", 0))
        user = json.loads(values.get("user", "{}"))
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if auth_date <= 0 or abs(int(time.time()) - auth_date) > TELEGRAM_AUTH_MAX_AGE_SECONDS:
        return None
    return user_id


def _signed_admin_user_id(user_id: str, signature: str, bot_token: str) -> int | None:
    try:
        parsed_user_id = int(user_id)
    except ValueError:
        return None
    expected_signature = hmac.new(
        bot_token.encode("utf-8"),
        f"tanellorn-admin:{parsed_user_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    return parsed_user_id


def _open_read_only_database(database_path: Path) -> sqlite3.Connection:
    if not database_path.exists():
        raise HTTPException(status_code=503, detail="База игры еще не подготовлена bot worker.")
    conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def create_app(settings_override: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Tanellorn Mini App", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    def settings() -> Settings:
        return settings_override or load_settings()

    def require_enabled(current: Settings) -> None:
        if not current.tanellorn_mini_app_enabled:
            raise HTTPException(status_code=404, detail="Tanellorn Mini App is disabled.")

    @app.get("/")
    @app.get("/tanellorn")
    def tanellorn_page() -> FileResponse:
        current = settings()
        require_enabled(current)
        return FileResponse(TANELLORN_PAGE, headers={"Cache-Control": "no-store"})

    @app.get("/api/tanellorn/state")
    def tanellorn_state(
        response: Response,
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        if current.tanellorn_mini_app_admin_only:
            user_id = _telegram_user_id(init_data, current.telegram_bot_token) or _signed_admin_user_id(
                admin_user_id,
                admin_signature,
                current.telegram_bot_token,
            )
            if user_id not in current.admin_telegram_ids:
                raise HTTPException(status_code=403, detail="Карта доступна только администратору.")
        with _open_read_only_database(current.database_path) as conn:
            response.headers["Cache-Control"] = "no-store"
            return build_tanellorn_map_state(conn)

    return app


app = create_app()


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("aventura_bot.web:app", host=host, port=port)


if __name__ == "__main__":
    main()
