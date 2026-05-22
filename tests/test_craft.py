import sqlite3
import unittest

from aventura_bot.db import from_json, init_db
from aventura_bot.services import game
from aventura_bot.services.turn_files import validate_result_payload


class CraftTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.telegram_id = 1001
        game.upsert_player(self.conn, self.telegram_id, "craft_tester")
        self.character = game.create_character(
            self.conn,
            self.telegram_id,
            "Хаул",
            "мужчина",
            "человек",
            "Мрачный наследник Каррок Манора, привыкший решать проблемы магией и сталью.",
            dict(game.DEFAULT_STATS),
            "Огненный шар",
            ["Магический ключ", "Вороний коготь", "Печатка Госпожи"],
        )

    def _open_turn(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO turns (title, status) VALUES ('Тестовый ход', 'open')"
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def _asset_token(self, name: str) -> str:
        for asset in game.list_craft_assets(self.conn, self.telegram_id):
            if asset["name"] == name:
                return asset["token"]
        raise AssertionError(f"Asset not found: {name}")

    def test_cannot_create_craft_without_open_turn(self):
        with self.assertRaisesRegex(ValueError, "нет открытого хода"):
            game.create_craft_request(
                self.conn,
                self.telegram_id,
                self._asset_token("Магический ключ"),
                self._asset_token("Огненный шар"),
            )

    def test_cannot_create_more_than_one_craft_per_turn(self):
        self._open_turn()
        game.create_craft_request(
            self.conn,
            self.telegram_id,
            self._asset_token("Магический ключ"),
            self._asset_token("Огненный шар"),
        )
        with self.assertRaisesRegex(ValueError, "уже есть крафт"):
            game.create_craft_request(
                self.conn,
                self.telegram_id,
                self._asset_token("Вороний коготь"),
                self._asset_token("Печатка Госпожи"),
            )

    def test_base_and_material_cannot_be_same_asset(self):
        self._open_turn()
        token = self._asset_token("Магический ключ")
        with self.assertRaisesRegex(ValueError, "одним и тем же"):
            game.create_craft_request(self.conn, self.telegram_id, token, token)

    def test_confirmed_craft_removes_both_assets(self):
        self._open_turn()
        game.create_craft_request(
            self.conn,
            self.telegram_id,
            self._asset_token("Магический ключ"),
            self._asset_token("Огненный шар"),
        )
        character = game.get_character_for_player(self.conn, self.telegram_id)
        inventory_names = [item["name"] for item in from_json(character["inventory_json"], [])]
        spell_names = [spell["name"] for spell in from_json(character["spells_json"], [])]

        self.assertNotIn("Магический ключ", inventory_names)
        self.assertNotIn("Огненный шар", spell_names)

    def test_confirmed_craft_removes_two_assets_from_same_collection(self):
        self._open_turn()
        game.create_craft_request(
            self.conn,
            self.telegram_id,
            self._asset_token("Магический ключ"),
            self._asset_token("Вороний коготь"),
        )
        character = game.get_character_for_player(self.conn, self.telegram_id)
        inventory_names = [item["name"] for item in from_json(character["inventory_json"], [])]

        self.assertNotIn("Магический ключ", inventory_names)
        self.assertNotIn("Вороний коготь", inventory_names)
        self.assertIn("Печатка Госпожи", inventory_names)

    def test_craft_requests_are_exported_with_turn(self):
        turn_id = self._open_turn()
        request = game.create_craft_request(
            self.conn,
            self.telegram_id,
            self._asset_token("Магический ключ"),
            self._asset_token("Огненный шар"),
        )

        payload = game.build_turn_export(self.conn, turn_id)

        self.assertEqual(len(payload["craft_requests"]), 1)
        self.assertEqual(payload["craft_requests"][0]["craft_request_id"], request["id"])
        self.assertEqual(payload["craft_requests"][0]["base"]["name"], "Магический ключ")
        self.assertEqual(payload["craft_requests"][0]["material"]["name"], "Огненный шар")

    def test_result_level_formula(self):
        self.assertEqual(game.craft_result_level(8, 4, "weak"), 9)
        self.assertEqual(game.craft_result_level(8, 4, "good"), 10)
        self.assertEqual(game.craft_result_level(8, 4, "strong"), 11)
        self.assertEqual(game.craft_result_level(1, 1, "weak"), 2)

    def test_craft_result_adds_asset_to_base_type_collection(self):
        turn_id = self._open_turn()
        request = game.create_craft_request(
            self.conn,
            self.telegram_id,
            self._asset_token("Магический ключ"),
            self._asset_token("Огненный шар"),
        )

        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [],
                "craft_results": [
                    {
                        "craft_request_id": request["id"],
                        "relationship": "strong",
                        "result": {
                            "type": "inventory",
                            "name": "Ключ Огненного Портала",
                            "level": 2,
                            "description": "Открывает короткие огненные разрывы.",
                        },
                    }
                ],
            },
        )
        character = game.get_character_for_player(self.conn, self.telegram_id)
        inventory = from_json(character["inventory_json"], [])

        self.assertIn("Ключ Огненного Портала", [item["name"] for item in inventory])

    def test_craft_result_must_keep_base_type(self):
        turn_id = self._open_turn()
        request = game.create_craft_request(
            self.conn,
            self.telegram_id,
            self._asset_token("Магический ключ"),
            self._asset_token("Огненный шар"),
        )

        with self.assertRaisesRegex(ValueError, "сохранять тип основы"):
            game.apply_result_payload(
                self.conn,
                {
                    "turn_id": turn_id,
                    "mission_results": [],
                    "craft_results": [
                        {
                            "craft_request_id": request["id"],
                            "relationship": "strong",
                            "result": {"type": "spells", "name": "Огненный портал", "level": 2},
                        }
                    ],
                },
            )

    def test_result_payload_accepts_craft_only_file(self):
        validate_result_payload(
            {
                "turn_id": 1,
                "craft_results": [
                    {
                        "craft_request_id": 1,
                        "relationship": "weak",
                        "result": {"type": "inventory", "name": "Слабый ключ", "level": 2},
                    }
                ],
            }
        )


if __name__ == "__main__":
    unittest.main()
