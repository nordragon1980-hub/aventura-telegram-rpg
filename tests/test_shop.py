import sqlite3
import unittest

from aventura_bot.db import init_db, to_json
from aventura_bot.services import game


class ShopTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def test_shop_prices_are_low_friction(self):
        self.assertEqual(game.shop_buy_price(5), 10)
        self.assertEqual(game.shop_sell_price(5), 5)

    def test_refresh_shop_replaces_all_system_stock(self):
        game.ensure_default_shop_items(self.conn)
        before_rows = self.conn.execute(
            "SELECT id FROM shop_items WHERE status = 'active' AND source != 'player_sale'"
        ).fetchall()
        before_ids = {int(row["id"]) for row in before_rows}
        refreshed = game.refresh_shop_for_new_turn(self.conn)
        active_rows = self.conn.execute(
            "SELECT id FROM shop_items WHERE status = 'active' AND source != 'player_sale'"
        ).fetchall()
        active_after_ids = {int(row["id"]) for row in active_rows}
        sold_after = self.conn.execute(
            "SELECT COUNT(*) AS count FROM shop_items WHERE status = 'sold' AND source != 'player_sale'"
        ).fetchone()["count"]

        self.assertEqual(len(before_ids), game.SHOP_SYSTEM_STOCK_SIZE)
        self.assertEqual(refreshed, game.SHOP_SYSTEM_STOCK_SIZE)
        self.assertEqual(len(active_after_ids), game.SHOP_SYSTEM_STOCK_SIZE)
        self.assertEqual(len(before_ids - active_after_ids), game.SHOP_SYSTEM_STOCK_SIZE)
        self.assertEqual(sold_after, game.SHOP_SYSTEM_STOCK_SIZE)

    def test_player_sale_expires_on_next_turn_refresh(self):
        player = game.upsert_player(self.conn, 7001, "seller")
        character_id = self.conn.execute(
            """
            INSERT INTO characters (player_id, name, gender, race, description, inventory_json, gold)
            VALUES (?, 'Лавочник', 'м', 'человек', 'Тестовый герой для лавки.', ?, 0)
            """,
            (
                player["id"],
                to_json([{"uid": "abc", "name": "Старый нож", "level": 2}]),
            ),
        ).lastrowid
        old_turn_id = self.conn.execute("INSERT INTO turns (title, status) VALUES ('Старый ход', 'closed')").lastrowid
        current_turn_id = self.conn.execute("INSERT INTO turns (title, status) VALUES ('Новый ход', 'open')").lastrowid
        self.conn.execute(
            """
            INSERT INTO shop_items (
                asset_type, name, level, asset_json, price, status, source, seller_character_id, created_turn_id
            )
            VALUES ('item', 'Старый нож', 2, ?, 4, 'active', 'player_sale', ?, ?)
            """,
            (to_json({"uid": "abc", "name": "Старый нож", "level": 2}), character_id, old_turn_id),
        )
        self.conn.commit()

        game.refresh_shop_for_new_turn(self.conn)
        listing = self.conn.execute("SELECT status FROM shop_items WHERE source = 'player_sale'").fetchone()

        self.assertEqual(current_turn_id, game.get_open_turn(self.conn)["id"])
        self.assertEqual(listing["status"], "sold")

    def test_system_shop_uses_fantasy_equipment_names(self):
        game.ensure_default_shop_items(self.conn)
        names = [
            row["name"]
            for row in self.conn.execute(
                "SELECT name FROM shop_items WHERE status = 'active' AND source != 'player_sale'"
            ).fetchall()
        ]
        equipment_words = {
            "меч",
            "топор",
            "лук",
            "арбалет",
            "кинжал",
            "копье",
            "молот",
            "кольчужная",
            "латы",
            "доспех",
            "плащ",
            "мантия",
            "сапоги",
            "перчатки",
            "пояс",
            "амулет",
            "кольцо",
            "щит",
            "рюкзак",
            "набор",
        }
        self.assertTrue(names)
        self.assertTrue(any(any(word in name.casefold() for word in equipment_words) for name in names))


if __name__ == "__main__":
    unittest.main()
