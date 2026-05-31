import sqlite3
import unittest

from aventura_bot.db import from_json, init_db, to_json
from aventura_bot.services import game


class CooldownTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        game.upsert_player(self.conn, 7001, "cooldown_first")
        game.upsert_player(self.conn, 7002, "cooldown_second")
        self.first = game.create_character(
            self.conn,
            7001,
            "Ирис",
            "женщина",
            "человек",
            "Искательница опасных дорог, которая носит с собой клинок и печать дозора.",
            dict(game.DEFAULT_STATS),
            "Ледяная стрела",
            ["Клинок", "Печать", "Фонарь"],
        )
        self.second = game.create_character(
            self.conn,
            7002,
            "Торн",
            "мужчина",
            "дворф",
            "Страж порогов, привыкший встречать угрозы с расчетом и железным терпением.",
            dict(game.DEFAULT_STATS),
            "Каменный щит",
            ["Молот", "Рог", "Карта"],
        )

    def _turn_mission(self, title: str = "Испытание") -> tuple[int, int]:
        turn_id = self.conn.execute(
            "INSERT INTO turns (title, status) VALUES (?, 'open')", (title,)
        ).lastrowid
        mission_id = self.conn.execute(
            """
            INSERT INTO missions (turn_id, title, description, difficulty, status)
            VALUES (?, 'Проверка', 'Цели миссии: удержать ворота.', 5, 'open')
            """,
            (turn_id,),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO mission_participants (mission_id, character_id) VALUES (?, ?)",
            (mission_id, self.first["id"]),
        )
        self.conn.execute(
            """
            INSERT INTO actions (turn_id, mission_id, character_id, action_text)
            VALUES (?, ?, ?, 'Ирис удерживает ворота и применяет свой клинок в опасный момент.')
            """,
            (turn_id, mission_id, self.first["id"]),
        )
        self.conn.commit()
        return int(turn_id), int(mission_id)

    def _use_item(self, turn_id: int, mission_id: int, name: str = "Клинок") -> None:
        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [
                    {
                        "mission_id": mission_id,
                        "status": "failed",
                        "player_results": [
                            {
                                "character_id": self.first["id"],
                                "check": {
                                    "success": False,
                                    "used_assets": [{"type": "inventory", "name": name}],
                                },
                                "changes": [],
                            }
                        ],
                    }
                ],
            },
        )

    def test_used_asset_is_inactive_for_one_following_turn(self):
        turn_id, mission_id = self._turn_mission()
        self._use_item(turn_id, mission_id)
        item = next(
            item for item in from_json(game.get_character_for_player(self.conn, 7001)["inventory_json"], [])
            if item["name"] == "Клинок"
        )

        self.assertEqual(item["cooldown_until_turn"], turn_id + 1)
        self.assertEqual(game.asset_cooldown_remaining(item, turn_id + 1), 1)
        self.assertEqual(game.asset_cooldown_remaining(item, turn_id + 2), 0)
        self.assertTrue(game.asset_is_active(item, turn_id + 2))
        displayed = game.character_assets_with_availability(
            self.conn, game.get_character_for_player(self.conn, 7001)
        )
        displayed_item = next(asset for asset in displayed["inventory"] if asset["name"] == "Клинок")
        self.assertEqual(displayed_item["cooldown_remaining"], 1)

    def test_inactive_asset_cannot_be_counted_again(self):
        turn_id, mission_id = self._turn_mission()
        self._use_item(turn_id, mission_id)
        next_turn, next_mission = self._turn_mission("Следующий ход")

        with self.assertRaisesRegex(ValueError, "находится на перезарядке"):
            self._use_item(next_turn, next_mission)

    def test_inactive_asset_is_ignored_in_hero_score(self):
        character = {"level": 3, "stats": dict(game.DEFAULT_STATS), "race": "человек"}
        score = game.calculate_hero_score(
            character,
            "сила",
            used_assets=[{"type": "inventory", "name": "Клинок", "level": 9, "active": False}],
        )

        self.assertEqual(score, 8)

    def test_shop_sale_and_buyback_preserve_cooldown(self):
        turn_id, mission_id = self._turn_mission()
        self._use_item(turn_id, mission_id)
        item = next(
            item for item in from_json(game.get_character_for_player(self.conn, 7001)["inventory_json"], [])
            if item["name"] == "Клинок"
        )
        sold = game.sell_inventory_item(self.conn, 7001, item["uid"])
        game.buy_back_shop_item(self.conn, 7001, sold["listing_id"])
        returned = next(
            item for item in from_json(game.get_character_for_player(self.conn, 7001)["inventory_json"], [])
            if item["name"] == "Клинок"
        )

        self.assertEqual(returned["cooldown_until_turn"], turn_id + 1)

    def test_shop_listing_cooldown_advances_with_turns(self):
        turn_id, mission_id = self._turn_mission()
        self._use_item(turn_id, mission_id)
        item = next(
            item for item in from_json(game.get_character_for_player(self.conn, 7001)["inventory_json"], [])
            if item["name"] == "Клинок"
        )
        sold = game.sell_inventory_item(self.conn, 7001, item["uid"])
        listed = next(item for item in game.list_shop_items(self.conn) if item["id"] == sold["listing_id"])
        self.assertEqual(listed["cooldown_remaining"], 1)

        self.conn.execute("INSERT INTO turns (title, status) VALUES ('Следующий ход', 'open')")
        self.conn.execute("INSERT INTO turns (title, status) VALUES ('Еще один ход', 'open')")
        self.conn.commit()
        listed = next(item for item in game.list_shop_items(self.conn) if item["id"] == sold["listing_id"])
        self.assertNotIn("cooldown_remaining", listed)

    def test_trade_preserves_cooldown(self):
        inventory = from_json(game.get_character_for_player(self.conn, 7001)["inventory_json"], [])
        inventory[0]["cooldown_until_turn"] = 5
        self.conn.execute(
            "UPDATE characters SET inventory_json = ? WHERE id = ?",
            (to_json(inventory), self.first["id"]),
        )
        self.conn.commit()
        game.start_trade(self.conn, 7001, "cooldown_second")
        game.offer_trade_item(self.conn, 7001, inventory[0]["uid"])
        game.accept_trade(self.conn, 7001)
        game.accept_trade(self.conn, 7002)

        received = next(
            item for item in from_json(game.get_character_for_player(self.conn, 7002)["inventory_json"], [])
            if item["name"] == inventory[0]["name"]
        )
        self.assertEqual(received["cooldown_until_turn"], 5)

    def test_craft_result_inherits_remaining_cooldown(self):
        turn_id, _mission_id = self._turn_mission()
        inventory = from_json(game.get_character_for_player(self.conn, 7001)["inventory_json"], [])
        inventory[0]["cooldown_until_turn"] = turn_id + 1
        self.conn.execute(
            "UPDATE characters SET inventory_json = ? WHERE id = ?",
            (to_json(inventory), self.first["id"]),
        )
        self.conn.commit()
        assets = game.list_craft_assets(self.conn, 7001)
        base = next(asset for asset in assets if asset["name"] == "Клинок")
        material = next(asset for asset in assets if asset["name"] == "Печать")
        request = game.create_craft_request(self.conn, 7001, base["token"], material["token"])
        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [],
                "craft_results": [
                    {
                        "craft_request_id": request["id"],
                        "relationship": "weak",
                        "result": {"type": "inventory", "name": "Клинок Печати", "level": 2},
                    }
                ],
            },
        )
        result = next(
            item for item in from_json(game.get_character_for_player(self.conn, 7001)["inventory_json"], [])
            if item["name"] == "Клинок Печати"
        )

        self.assertEqual(result["cooldown_until_turn"], turn_id + 1)
        self.assertEqual(game.asset_cooldown_remaining(result, turn_id + 1), 1)

    def test_tavern_price_scales_with_level_and_cooling_assets_and_clears_them(self):
        turn_id, _mission_id = self._turn_mission()
        character = game.get_character_for_player(self.conn, 7001)
        inventory = from_json(character["inventory_json"], [])
        inventory[0].update({"level": 8, "cooldown_until_turn": turn_id + 1})
        spells = from_json(character["spells_json"], [])
        spells[0].update({"level": 4, "cooldown_until_turn": turn_id + 1})
        self.conn.execute(
            "UPDATE characters SET level = 10, gold = 20, inventory_json = ?, spells_json = ? WHERE id = ?",
            (to_json(inventory), to_json(spells), self.first["id"]),
        )
        self.conn.commit()

        offer = game.tavern_rest_offer(self.conn, 7001)
        self.assertEqual(offer["price"], 6)  # ceil(10 / 4) + ceil((8 + 4) / 4)
        result = game.rest_in_tavern(self.conn, 7001)
        refreshed = game.character_assets_with_availability(
            self.conn, game.get_character_for_player(self.conn, 7001)
        )

        self.assertEqual(result["gold"], 14)
        self.assertTrue(all(asset["active"] for asset in refreshed["inventory"] + refreshed["spells"]))


if __name__ == "__main__":
    unittest.main()
