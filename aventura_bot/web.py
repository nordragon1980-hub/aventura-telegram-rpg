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
from pydantic import BaseModel

from aventura_bot.config import Settings, load_settings
from aventura_bot.db import connect, from_json, row_to_dict
from aventura_bot.services.game import (
    build_tanellorn_map_state,
    buy_back_shop_item,
    buy_shop_item,
    character_assets_with_availability,
    get_character_for_player,
    get_open_turn,
    join_mission,
    list_shop_items,
    list_public_roster,
    player_can_buy_back,
    rest_in_tavern,
    sell_inventory_item,
    sell_mount,
    sell_pet,
    submit_action,
    tavern_rest_offer,
)


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


def _signed_admin_user_id(user_id: str, expires: str, signature: str, bot_token: str) -> int | None:
    try:
        parsed_user_id = int(user_id)
        parsed_expires = int(expires)
    except ValueError:
        return None
    now = int(time.time())
    if parsed_expires < now or parsed_expires > now + TELEGRAM_AUTH_MAX_AGE_SECONDS:
        return None
    expected_signature = hmac.new(
        bot_token.encode("utf-8"),
        f"tanellorn-admin:{parsed_user_id}:{parsed_expires}".encode("utf-8"),
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


def _open_write_database(database_path: Path) -> sqlite3.Connection:
    if not database_path.exists():
        raise HTTPException(status_code=503, detail="База игры еще не подготовлена bot worker.")
    return connect(database_path)


class TanellornActionRequest(BaseModel):
    action_text: str


class TanellornSellRequest(BaseModel):
    asset_type: str
    token: str


def create_app(settings_override: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Tanellorn Mini App", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")

    def settings() -> Settings:
        return settings_override or load_settings()

    def require_enabled(current: Settings) -> None:
        if not current.tanellorn_mini_app_enabled:
            raise HTTPException(status_code=404, detail="Tanellorn Mini App is disabled.")

    def authenticated_user_id(
        current: Settings,
        init_data: str,
        admin_user_id: str,
        admin_expires: str,
        admin_signature: str,
    ) -> int:
        user_id = _telegram_user_id(init_data, current.telegram_bot_token)
        if user_id is None and current.tanellorn_mini_app_admin_only:
            user_id = _signed_admin_user_id(admin_user_id, admin_expires, admin_signature, current.telegram_bot_token)
        if user_id is None:
            raise HTTPException(status_code=403, detail="Открой Танелорн из кнопки Telegram-бота.")
        if current.tanellorn_mini_app_admin_only and user_id not in current.admin_telegram_ids:
            raise HTTPException(status_code=403, detail="Карта доступна только администратору.")
        return user_id

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
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        if current.tanellorn_mini_app_admin_only:
            authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        with _open_read_only_database(current.database_path) as conn:
            response.headers["Cache-Control"] = "no-store"
            return build_tanellorn_map_state(conn)

    @app.get("/api/tanellorn/me")
    def tanellorn_me(
        response: Response,
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        user_id = authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        with _open_read_only_database(current.database_path) as conn:
            response.headers["Cache-Control"] = "no-store"
            return _build_player_view(conn, user_id)

    @app.get("/api/tanellorn/roster")
    def tanellorn_roster(
        response: Response,
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        with _open_read_only_database(current.database_path) as conn:
            response.headers["Cache-Control"] = "no-store"
            return {"heroes": list_public_roster(conn)}

    @app.post("/api/tanellorn/missions/{mission_id}/join")
    def tanellorn_join_mission(
        mission_id: int,
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        user_id = authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        try:
            with _open_write_database(current.database_path) as conn:
                mission = join_mission(conn, user_id, mission_id)
                player = _build_player_view(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        switched = mission.get("switched_from")
        if switched:
            message = f"Выбрана миссия: {mission['title']}. Предыдущая миссия заменена."
        else:
            message = f"Выбрана миссия: {mission['title']}."
        return {"message": message, "action_cleared": bool(mission.get("action_cleared")), "player": player}

    @app.post("/api/tanellorn/action")
    def tanellorn_submit_action(
        payload: TanellornActionRequest,
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        user_id = authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        try:
            with _open_write_database(current.database_path) as conn:
                mission = submit_action(conn, user_id, payload.action_text)
                player = _build_player_view(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"message": f"Действие принято для миссии: {mission['title']}.", "player": player}

    @app.get("/api/tanellorn/shop")
    def tanellorn_shop(
        response: Response,
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        user_id = authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        with _open_write_database(current.database_path) as conn:
            response.headers["Cache-Control"] = "no-store"
            return _build_shop_view(conn, user_id)

    @app.post("/api/tanellorn/shop/{shop_item_id}/buy")
    def tanellorn_buy_shop_item(
        shop_item_id: int,
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        user_id = authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        try:
            with _open_write_database(current.database_path) as conn:
                result = buy_shop_item(conn, user_id, shop_item_id)
                view = _build_shop_view(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"message": f"Куплено: {result['item']['name']}.", "shop": view}

    @app.post("/api/tanellorn/shop/{shop_item_id}/buyback")
    def tanellorn_buyback_shop_item(
        shop_item_id: int,
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        user_id = authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        try:
            with _open_write_database(current.database_path) as conn:
                result = buy_back_shop_item(conn, user_id, shop_item_id)
                view = _build_shop_view(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"message": f"Выкуплено обратно: {result['item']['name']}.", "shop": view}

    @app.post("/api/tanellorn/shop/sell")
    def tanellorn_sell_asset(
        payload: TanellornSellRequest,
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        user_id = authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        try:
            with _open_write_database(current.database_path) as conn:
                if payload.asset_type == "item":
                    result = sell_inventory_item(conn, user_id, payload.token)
                elif payload.asset_type == "pet":
                    result = sell_pet(conn, user_id, payload.token)
                elif payload.asset_type == "mount":
                    result = sell_mount(conn, user_id, payload.token)
                else:
                    raise ValueError("Этот тип актива нельзя продавать в лавке.")
                view = _build_shop_view(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "message": f"Продано: {result['item']['name']} за {result['price']} дублонов.",
            "listing_id": result["listing_id"],
            "shop": view,
        }

    @app.post("/api/tanellorn/tavern/rest")
    def tanellorn_rest_in_tavern(
        init_data: str = Query(default=""),
        admin_user_id: str = Query(default=""),
        admin_expires: str = Query(default=""),
        admin_signature: str = Query(default=""),
    ) -> dict:
        current = settings()
        require_enabled(current)
        user_id = authenticated_user_id(current, init_data, admin_user_id, admin_expires, admin_signature)
        try:
            with _open_write_database(current.database_path) as conn:
                result = rest_in_tavern(conn, user_id)
                view = _build_shop_view(conn, user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "message": (
                f"Отдых завершен. Восстановлено активов: {result['asset_count']}. "
                f"Потрачено: {result['price']} дублонов."
            ),
            "shop": view,
        }

    return app


app = create_app()


def _build_player_view(conn: sqlite3.Connection, telegram_id: int) -> dict:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        return {"character": None, "current_mission": None, "latest_result": None}
    assets = character_assets_with_availability(conn, character)
    current_mission = _current_player_mission(conn, int(character["id"]))
    return {
        "character": {
            "id": int(character["id"]),
            "name": str(character["name"]),
            "gender": str(character["gender"]),
            "race": str(character["race"]),
            "description": str(character["description"]),
            "level": int(character["level"]),
            "gold": int(character["gold"]),
            "stats": from_json(character.get("stats_json"), {}),
            "statuses": from_json(character.get("status_json"), {}),
            "assets": assets,
        },
        "current_mission": current_mission,
        "latest_result": _latest_player_result(conn, int(character["id"])),
    }


def _current_player_mission(conn: sqlite3.Connection, character_id: int) -> dict | None:
    turn = get_open_turn(conn)
    if not turn:
        return None
    row = conn.execute(
        """
        SELECT missions.*, actions.action_text, actions.submitted_at
        FROM mission_participants
        JOIN missions ON missions.id = mission_participants.mission_id
        LEFT JOIN actions
          ON actions.turn_id = missions.turn_id
         AND actions.mission_id = missions.id
         AND actions.character_id = mission_participants.character_id
        WHERE mission_participants.character_id = ?
          AND missions.turn_id = ?
        ORDER BY mission_participants.joined_at DESC
        LIMIT 1
        """,
        (character_id, turn["id"]),
    ).fetchone()
    mission = row_to_dict(row)
    if not mission:
        return None
    return {
        "id": int(mission["id"]),
        "title": str(mission["title"]),
        "type": str(mission.get("mission_type") or "standard"),
        "subtype": mission.get("mission_subtype"),
        "locked": bool(mission.get("party_locked")),
        "action_text": mission.get("action_text") or "",
    }


def _latest_player_result(conn: sqlite3.Connection, character_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT results.result_json, missions.title AS mission_title, turns.title AS turn_title
        FROM results
        JOIN missions ON missions.id = results.mission_id
        JOIN turns ON turns.id = results.turn_id
        JOIN mission_participants ON mission_participants.mission_id = missions.id
        WHERE mission_participants.character_id = ?
        ORDER BY results.id DESC
        LIMIT 1
        """,
        (character_id,),
    ).fetchone()
    if not row:
        return None
    result = from_json(row["result_json"], {})
    player_result = next(
        (
            value
            for value in result.get("player_results", [])
            if int(value.get("character_id", -1)) == character_id
        ),
        None,
    )
    return {
        "turn_title": str(row["turn_title"]),
        "mission_title": str(row["mission_title"]),
        "status": result.get("status"),
        "public_summary": result.get("public_summary", ""),
        "player_result": player_result,
    }


def _build_shop_view(conn: sqlite3.Connection, telegram_id: int) -> dict:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise HTTPException(status_code=400, detail="Сначала создай персонажа.")
    assets = character_assets_with_availability(conn, character)
    items = list_shop_items(conn)
    return {
        "gold": int(character["gold"]),
        "items": [
            {
                "id": int(item["id"]),
                "asset_type": str(item.get("asset_type") or "item"),
                "name": str(item["name"]),
                "level": int(item["level"]),
                "price": int(item["price"]),
                "source": str(item.get("source") or "system"),
                "cooldown_remaining": int(item.get("cooldown_remaining", 0) or 0),
                "can_buy_back": player_can_buy_back(conn, telegram_id, int(item["id"])),
            }
            for item in items
        ],
        "sellables": {
            "inventory": assets["inventory"],
            "pets": assets["pets"],
            "mounts": assets["mounts"],
        },
        "tavern": tavern_rest_offer(conn, telegram_id),
    }


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("aventura_bot.web:app", host=host, port=port)


if __name__ == "__main__":
    main()
