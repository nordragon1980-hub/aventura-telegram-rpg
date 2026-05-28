import hashlib
import hmac
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from fastapi.testclient import TestClient

from aventura_bot.bot import _effective_mission_ui_mode, _main_menu_keyboard, _tanellorn_inline_keyboard
from aventura_bot.config import Settings, _parse_bool, _parse_mission_ui_mode
from aventura_bot.db import connect, from_json, init_db, to_json
from aventura_bot.services import game
from aventura_bot.services.game import build_tanellorn_map_state
from aventura_bot.web import _telegram_user_id, create_app


def _settings(**overrides) -> Settings:
    defaults = {
        "telegram_bot_token": "test-token",
        "admin_telegram_ids": {1001},
        "game_chat_id": None,
        "tanellorn_mini_app_enabled": False,
        "tanellorn_mini_app_admin_only": True,
        "tanellorn_mini_app_url": "",
        "mission_ui_mode": "legacy",
        "database_path": Path("data/test.sqlite"),
        "exports_dir": Path("data/exports"),
        "imports_dir": Path("data/imports"),
        "backups_dir": Path("data/backups"),
        "seeds_dir": Path("data/seeds"),
        "workbench_dir": Path("data/workbench"),
        "art_dir": Path("data/art"),
        "chronicle_dir": Path("data/chronicle"),
        "pending_imports_dir": Path("data/imports/pending"),
        "processed_imports_dir": Path("data/imports/processed"),
        "failed_imports_dir": Path("data/imports/failed"),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _signed_init_data(user_id: int, token: str = "test-token") -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "query",
        "user": json.dumps({"id": user_id}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(values)


class TanellornFlagTests(unittest.TestCase):
    def test_safe_defaults_and_mode_validation(self):
        self.assertFalse(_parse_bool("", False))
        self.assertTrue(_parse_bool("", True))
        self.assertEqual(_parse_mission_ui_mode(""), "legacy")
        self.assertEqual(_parse_mission_ui_mode("both"), "both")
        with self.assertRaises(RuntimeError):
            _parse_mission_ui_mode("map")

    def test_button_is_admin_only_when_configured(self):
        settings = _settings(
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_url="https://example.test/tanellorn",
            mission_ui_mode="both",
        )
        admin_keyboard = _tanellorn_inline_keyboard(settings, 1001)
        self.assertIsNotNone(admin_keyboard)
        admin_url = admin_keyboard.inline_keyboard[0][0].web_app.url
        self.assertIn("admin_user_id=1001", admin_url)
        self.assertIn("admin_expires=", admin_url)
        self.assertIn("admin_signature=", admin_url)
        self.assertIsNone(_tanellorn_inline_keyboard(settings, 1002))
        self.assertEqual(_effective_mission_ui_mode(settings, 1001), "both")
        self.assertEqual(_effective_mission_ui_mode(settings, 1002), "legacy")

    def test_disabled_or_missing_url_keeps_legacy_ui(self):
        enabled_without_url = _settings(tanellorn_mini_app_enabled=True, mission_ui_mode="miniapp")
        self.assertIsNone(_tanellorn_inline_keyboard(enabled_without_url, 1001))
        self.assertEqual(_effective_mission_ui_mode(enabled_without_url, 1001), "legacy")
        keyboard = _main_menu_keyboard(enabled_without_url, 1001)
        self.assertEqual(len(keyboard.keyboard), 4)


class TanellornStateTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        turn_id = self.conn.execute(
            "INSERT INTO turns (title, status) VALUES ('Карта города', 'open')"
        ).lastrowid
        self.mission_id = self.conn.execute(
            """
            INSERT INTO missions (turn_id, title, description, difficulty, status, max_participants)
            VALUES (?, 'Башня смотрителя', 'Спасти смотрителя из башни.', 12, 'open', 3)
            """,
            (turn_id,),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO mission_participants (mission_id, character_id) VALUES (?, 1)",
            (self.mission_id,),
        )
        self.conn.commit()

    def test_open_missions_are_exposed_as_map_points(self):
        state = build_tanellorn_map_state(self.conn)
        self.assertEqual(state["mode"], "tanellorn_map_v1")
        self.assertEqual(state["turn"]["title"], "Карта города")
        mission = state["missions"][0]
        self.assertEqual(mission["title"], "Башня смотрителя")
        self.assertEqual(mission["difficulty_label"], "Сложно")
        self.assertNotIn("difficulty", mission)
        self.assertEqual(mission["participants_count"], 1)
        self.assertEqual(mission["participants_limit"], 3)
        self.assertIn("x", mission)
        self.assertIn("y", mission)


class TanellornTelegramAuthTests(unittest.TestCase):
    def test_signed_admin_init_data_can_be_read(self):
        init_data = _signed_init_data(1001)
        self.assertEqual(_telegram_user_id(init_data, "test-token"), 1001)
        self.assertIsNone(_telegram_user_id(f"{init_data}&hash=wrong", "test-token"))


class TanellornWebRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "tanellorn.sqlite"
        with connect(self.database_path) as conn:
            init_db(conn)
            game.upsert_player(conn, 1001, "master")
            self.character = game.create_character(
                conn,
                1001,
                "Элин",
                "женский",
                "человек",
                "Следопыт Авентуры, привыкшая охранять городские ворота и вести отряд через опасность.",
                dict(game.DEFAULT_STATS),
                "Огненная нить",
                ["Клинок", "Фонарь", "Карта"],
            )
            turn_id = conn.execute(
                "INSERT INTO turns (title, status) VALUES ('Ночной дозор', 'open')"
            ).lastrowid
            self.turn_id = int(turn_id)
            self.mission_id = conn.execute(
                """
                INSERT INTO missions (turn_id, title, description, difficulty, status)
                VALUES (?, 'Врата рынка', 'Удержать ворота.', 7, 'open')
                """,
                (turn_id,),
            ).lastrowid
            self.second_mission_id = conn.execute(
                """
                INSERT INTO missions (turn_id, title, description, difficulty, status)
                VALUES (?, 'Мост', 'Удержать мост.', 8, 'open')
                """,
                (turn_id,),
            ).lastrowid
            conn.commit()

    def test_public_preview_page_and_state_route(self):
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=False,
        )
        client = TestClient(create_app(settings))
        page_response = client.get("/tanellorn")
        self.assertIn("Танелорн", page_response.text)
        self.assertEqual(page_response.headers["cache-control"], "no-store")
        state_response = client.get("/api/tanellorn/state")
        self.assertEqual(state_response.headers["cache-control"], "no-store")
        payload = state_response.json()
        self.assertEqual(payload["missions"][0]["title"], "Врата рынка")

    def test_admin_only_api_rejects_unsigned_browser_request(self):
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
        )
        response = TestClient(create_app(settings)).get("/api/tanellorn/state")
        self.assertEqual(response.status_code, 403)

    def test_admin_only_api_accepts_signed_admin_request(self):
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
        )
        response = TestClient(create_app(settings)).get(
            "/api/tanellorn/state",
            params={"init_data": _signed_init_data(1001)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["missions"][0]["title"], "Врата рынка")

    def test_admin_only_api_accepts_signed_button_access(self):
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
            tanellorn_mini_app_url="https://example.test/tanellorn",
        )
        button_url = _tanellorn_inline_keyboard(settings, 1001).inline_keyboard[0][0].web_app.url
        query = dict(parse_qsl(urlsplit(button_url).query))
        response = TestClient(create_app(settings)).get("/api/tanellorn/state", params=query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["missions"][0]["title"], "Врата рынка")

    def test_admin_only_api_rejects_tampered_button_access(self):
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
        )
        response = TestClient(create_app(settings)).get(
            "/api/tanellorn/state",
            params={"admin_user_id": "1001", "admin_signature": "wrong"},
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_read_hero_and_roster_from_mini_app(self):
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
        )
        client = TestClient(create_app(settings))
        params = {"init_data": _signed_init_data(1001)}
        self.assertEqual(client.get("/api/tanellorn/me", params=params).json()["character"]["name"], "Элин")
        self.assertEqual(client.get("/api/tanellorn/roster", params=params).json()["heroes"][0]["name"], "Элин")

    def test_hero_view_includes_latest_personal_result(self):
        with connect(self.database_path) as conn:
            conn.execute(
                "INSERT INTO mission_participants (mission_id, character_id) VALUES (?, ?)",
                (self.mission_id, self.character["id"]),
            )
            conn.execute(
                "INSERT INTO results (turn_id, mission_id, result_json) VALUES (?, ?, ?)",
                (
                    self.turn_id,
                    self.mission_id,
                    json.dumps(
                        {
                            "status": "success",
                            "public_summary": "Ворота удержаны.",
                            "player_results": [
                                {
                                    "character_id": self.character["id"],
                                    "message": "Элин прикрыла патруль.",
                                    "changes": [{"field": "gold", "delta": 3}],
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.commit()
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
        )
        response = TestClient(create_app(settings)).get(
            "/api/tanellorn/me",
            params={"init_data": _signed_init_data(1001)},
        )
        result = response.json()["latest_result"]
        self.assertEqual(result["public_summary"], "Ворота удержаны.")
        self.assertEqual(result["player_result"]["message"], "Элин прикрыла патруль.")

    def test_mini_app_can_join_submit_and_replace_action(self):
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
            tanellorn_mini_app_url="https://example.test/tanellorn",
        )
        client = TestClient(create_app(settings))
        button_url = _tanellorn_inline_keyboard(settings, 1001).inline_keyboard[0][0].web_app.url
        params = dict(parse_qsl(urlsplit(button_url).query))
        joined = client.post(f"/api/tanellorn/missions/{self.mission_id}/join", params=params)
        self.assertEqual(joined.status_code, 200)
        action_text = "Элин удерживает ворота, закрепляет створки цепью и предупреждает стражу о подходе врагов. " * 2
        sent = client.post("/api/tanellorn/action", params=params, json={"action_text": action_text})
        self.assertEqual(sent.status_code, 200)
        self.assertEqual(sent.json()["player"]["current_mission"]["action_text"], action_text)

        replacement = action_text.replace("ворота", "мост")
        replaced = client.post("/api/tanellorn/action", params=params, json={"action_text": replacement})
        self.assertEqual(replaced.json()["player"]["current_mission"]["action_text"], replacement)

    def test_changing_mission_from_mini_app_clears_previous_action(self):
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
        )
        client = TestClient(create_app(settings))
        params = {"init_data": _signed_init_data(1001)}
        client.post(f"/api/tanellorn/missions/{self.mission_id}/join", params=params)
        action_text = "Элин удерживает ворота, закрепляет створки цепью и предупреждает стражу о подходе врагов. " * 2
        client.post("/api/tanellorn/action", params=params, json={"action_text": action_text})

        switched = client.post(f"/api/tanellorn/missions/{self.second_mission_id}/join", params=params)
        self.assertTrue(switched.json()["action_cleared"])
        self.assertEqual(switched.json()["player"]["current_mission"]["id"], self.second_mission_id)
        self.assertEqual(switched.json()["player"]["current_mission"]["action_text"], "")

    def test_mini_app_shop_can_buy_sell_and_buy_back_item(self):
        with connect(self.database_path) as conn:
            conn.execute("UPDATE characters SET gold = 20 WHERE id = ?", (self.character["id"],))
            listing_id = conn.execute(
                """
                INSERT INTO shop_items (asset_type, name, level, asset_json, price, status, source)
                VALUES ('item', 'Компас дозора', 1, '{}', 2, 'active', 'system')
                """
            ).lastrowid
            conn.commit()
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
        )
        client = TestClient(create_app(settings))
        params = {"init_data": _signed_init_data(1001)}
        bought = client.post(f"/api/tanellorn/shop/{listing_id}/buy", params=params)
        self.assertEqual(bought.status_code, 200)
        bought_item = next(
            item for item in bought.json()["shop"]["sellables"]["inventory"] if item["name"] == "Компас дозора"
        )
        sold = client.post(
            "/api/tanellorn/shop/sell",
            params=params,
            json={"asset_type": "item", "token": bought_item["uid"]},
        )
        self.assertEqual(sold.status_code, 200)
        player_listing = next(
            item for item in sold.json()["shop"]["items"] if item["id"] == sold.json()["listing_id"]
        )
        self.assertEqual(player_listing["source"], "player_sale")
        self.assertTrue(player_listing["can_buy_back"])
        self.assertNotIn("companions", sold.json()["shop"]["sellables"])
        buyback = client.post(f"/api/tanellorn/shop/{sold.json()['listing_id']}/buyback", params=params)
        self.assertEqual(buyback.status_code, 200)
        self.assertIn(
            "Компас дозора",
            [item["name"] for item in buyback.json()["shop"]["sellables"]["inventory"]],
        )

    def test_mini_app_tavern_rest_restores_cooling_asset(self):
        with connect(self.database_path) as conn:
            character = game.get_character_for_player(conn, 1001)
            inventory = from_json(character["inventory_json"], [])
            inventory[0]["cooldown_until_turn"] = self.turn_id + 2
            conn.execute(
                "UPDATE characters SET gold = 10, inventory_json = ? WHERE id = ?",
                (to_json(inventory), self.character["id"]),
            )
            conn.commit()
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
        )
        client = TestClient(create_app(settings))
        params = {"init_data": _signed_init_data(1001)}
        offer = client.get("/api/tanellorn/shop", params=params).json()["tavern"]
        self.assertTrue(offer["available"])
        rested = client.post("/api/tanellorn/tavern/rest", params=params)
        self.assertEqual(rested.status_code, 200)
        self.assertFalse(rested.json()["shop"]["tavern"]["available"])

    def test_mini_app_can_create_current_turn_craft_request(self):
        settings = _settings(
            database_path=self.database_path,
            tanellorn_mini_app_enabled=True,
            tanellorn_mini_app_admin_only=True,
        )
        client = TestClient(create_app(settings))
        params = {"init_data": _signed_init_data(1001)}
        assets = client.get("/api/tanellorn/craft", params=params).json()["assets"]
        crafted = client.post(
            "/api/tanellorn/craft",
            params=params,
            json={"base_token": assets[0]["token"], "material_token": assets[1]["token"]},
        )
        self.assertEqual(crafted.status_code, 200)
        request = crafted.json()["craft"]["request"]
        self.assertEqual(request["base"]["name"], assets[0]["name"])
        self.assertEqual(request["material"]["name"], assets[1]["name"])
        repeated = client.post(
            "/api/tanellorn/craft",
            params=params,
            json={"base_token": assets[1]["token"], "material_token": assets[2]["token"]},
        )
        self.assertEqual(repeated.status_code, 400)


if __name__ == "__main__":
    unittest.main()
