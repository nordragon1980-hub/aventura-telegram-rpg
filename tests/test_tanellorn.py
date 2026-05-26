import hashlib
import hmac
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from aventura_bot.bot import _effective_mission_ui_mode, _main_menu_keyboard, _tanellorn_inline_keyboard
from aventura_bot.config import Settings, _parse_bool, _parse_mission_ui_mode
from aventura_bot.db import connect, init_db
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
        self.assertIsNotNone(_tanellorn_inline_keyboard(settings, 1001))
        self.assertIsNone(_tanellorn_inline_keyboard(settings, 1002))
        self.assertEqual(_effective_mission_ui_mode(settings, 1001), "both")
        self.assertEqual(_effective_mission_ui_mode(settings, 1002), "legacy")

    def test_disabled_or_missing_url_keeps_legacy_ui(self):
        enabled_without_url = _settings(tanellorn_mini_app_enabled=True, mission_ui_mode="miniapp")
        self.assertIsNone(_tanellorn_inline_keyboard(enabled_without_url, 1001))
        self.assertEqual(_effective_mission_ui_mode(enabled_without_url, 1001), "legacy")
        keyboard = _main_menu_keyboard(enabled_without_url, 1001)
        self.assertEqual(len(keyboard.keyboard), 3)


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
        self.assertEqual(mission["difficulty"], 12)
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
            turn_id = conn.execute(
                "INSERT INTO turns (title, status) VALUES ('Ночной дозор', 'open')"
            ).lastrowid
            conn.execute(
                """
                INSERT INTO missions (turn_id, title, description, difficulty, status)
                VALUES (?, 'Врата рынка', 'Удержать ворота.', 7, 'open')
                """,
                (turn_id,),
            )
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


if __name__ == "__main__":
    unittest.main()
