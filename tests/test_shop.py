import sqlite3
import unittest

from aventura_bot.db import init_db
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
        before = self.conn.execute(
            "SELECT COUNT(*) AS count FROM shop_items WHERE status = 'active' AND source != 'player_sale'"
        ).fetchone()["count"]
        refreshed = game.refresh_shop_for_new_turn(self.conn)
        active_after = self.conn.execute(
            "SELECT COUNT(*) AS count FROM shop_items WHERE status = 'active' AND source != 'player_sale'"
        ).fetchone()["count"]
        sold_after = self.conn.execute(
            "SELECT COUNT(*) AS count FROM shop_items WHERE status = 'sold' AND source != 'player_sale'"
        ).fetchone()["count"]

        self.assertEqual(before, game.SHOP_SYSTEM_STOCK_SIZE)
        self.assertEqual(refreshed, before)
        self.assertEqual(active_after, game.SHOP_SYSTEM_STOCK_SIZE)
        self.assertEqual(sold_after, before)


if __name__ == "__main__":
    unittest.main()
