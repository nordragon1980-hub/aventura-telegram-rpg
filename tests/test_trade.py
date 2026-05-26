import sqlite3
import unittest

from aventura_bot.db import from_json, init_db, to_json
from aventura_bot.services import game


class TradeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        game.upsert_player(self.conn, 1001, "first_player")
        game.upsert_player(self.conn, 1002, "second_player")
        self.first = game.create_character(
            self.conn,
            1001,
            "Ада",
            "женщина",
            "человек",
            "Путешественница, которая внимательно выбирает союзников и держит слово.",
            dict(game.DEFAULT_STATS),
            "Искра",
            ["нож", "плащ", "мел"],
        )
        self.second = game.create_character(
            self.conn,
            1002,
            "Бор",
            "мужчина",
            "дворф",
            "Опытный разведчик, способный вывести отряд с самой опасной дороги.",
            dict(game.DEFAULT_STATS),
            "Щит",
            ["меч", "фонарь", "ключ"],
        )
        self.conn.execute(
            "UPDATE characters SET companions_json = ? WHERE id = ?",
            (to_json([{"name": "Мира", "level": 3}]), self.first["id"]),
        )
        self.conn.commit()

    def test_companion_can_be_transferred_in_trade(self):
        game.start_trade(self.conn, 1001, "second_player")
        trade = game.offer_trade_companion(self.conn, 1001, "Мира")
        self.assertEqual(from_json(trade["initiator_companions_json"], []), ["Мира"])

        _, completed = game.accept_trade(self.conn, 1001)
        self.assertFalse(completed)
        _, completed = game.accept_trade(self.conn, 1002)
        self.assertTrue(completed)

        first = game.get_character_for_player(self.conn, 1001)
        second = game.get_character_for_player(self.conn, 1002)
        self.assertEqual(from_json(first["companions_json"], []), [])
        self.assertEqual(from_json(second["companions_json"], []), [{"name": "Мира", "level": 3}])

    def test_companion_can_be_removed_from_offer(self):
        game.start_trade(self.conn, 1001, "second_player")
        game.offer_trade_companion(self.conn, 1001, "Мира")
        trade = game.remove_trade_companion(self.conn, 1001, "Мира")
        self.assertEqual(from_json(trade["initiator_companions_json"], []), [])


if __name__ == "__main__":
    unittest.main()
