import sqlite3
import unittest

from aventura_bot.db import from_json, init_db
from aventura_bot.services import game


class BossRewardTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.telegram_id = 501
        game.upsert_player(self.conn, self.telegram_id, "boss_tester")
        self.character = game.create_character(
            self.conn,
            self.telegram_id,
            "Рион",
            "мужской",
            "человек",
            "Авантюрист в сером плаще, который привык держаться рядом с опасностью.",
            dict(game.DEFAULT_STATS),
            "Огненная стрела",
            ["кинжал", "плащ", "мел"],
        )

    def _create_final_boss_phase(self, difficulty: int = 60) -> tuple[int, int]:
        turn_id = self.conn.execute(
            "INSERT INTO turns (title, status) VALUES ('Финал босса', 'open')"
        ).lastrowid
        mission_id = self.conn.execute(
            """
            INSERT INTO missions (
                turn_id, title, description, mission_type, mission_subtype,
                phase, max_phase, max_participants, boss_name, boss_theme,
                continuation_key, difficulty, status
            )
            VALUES (?, 'Сердце босса', 'Финальная фаза.', 'boss', 'phased',
                3, 3, 4, 'Сердце', 'финал', 'boss-heart', ?, 'open')
            """,
            (turn_id, difficulty),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO mission_participants (mission_id, character_id) VALUES (?, ?)",
            (mission_id, self.character["id"]),
        )
        self.conn.commit()
        return int(turn_id), int(mission_id)

    def test_boss_final_reward_bounds_are_difficulty_quarter_with_variance(self):
        self.assertEqual(game.boss_final_reward_level_bounds(60), (12, 18))
        self.assertEqual(game.boss_trophy_level_bounds(60), (16, 24))

    def test_final_boss_export_uses_boss_reward_roll(self):
        turn_id, _mission_id = self._create_final_boss_phase(60)

        payload = game.build_turn_export(self.conn, turn_id)
        reward_roll = payload["missions"][0]["participants"][0]["reward_roll"]

        self.assertEqual(reward_roll["source"], "backend_boss_final_roll")
        self.assertGreaterEqual(reward_roll["level"], 12)
        self.assertLessEqual(reward_roll["level"], 18)
        self.assertEqual(reward_roll["stat_delta"], reward_roll["level"])

    def test_boss_final_stat_reward_uses_stat_delta(self):
        turn_id, mission_id = self._create_final_boss_phase(60)
        reward_roll = {
            "pool": "common",
            "level": 15,
            "allowed_types": ["stat"],
            "stat_delta": 15,
            "source": "backend_boss_final_roll",
        }

        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [
                    {
                        "mission_id": mission_id,
                        "status": "completed",
                        "public_summary": "Босс повержен.",
                        "player_results": [
                            {
                                "character_id": self.character["id"],
                                "message": "Рион удержал финальный удар.",
                                "check": {"success": True},
                                "reward_roll": reward_roll,
                                "changes": [
                                    {"field": "stat", "stat": "сила", "delta": 15, "reason": "Финал босса"}
                                ],
                            }
                        ],
                    }
                ],
            },
        )

        character = game.get_character_for_player(self.conn, self.telegram_id)
        stats = from_json(character["stats_json"], {})
        self.assertEqual(stats["сила"], game.DEFAULT_STATS["сила"] + 15)

    def test_boss_trophy_uses_difficulty_third_with_variance(self):
        turn_id, mission_id = self._create_final_boss_phase(60)

        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [
                    {
                        "mission_id": mission_id,
                        "status": "completed",
                        "public_summary": "Босс повержен.",
                        "player_results": [
                            {
                                "character_id": self.character["id"],
                                "message": "Рион забрал трофей.",
                                "check": {"success": True},
                                "reward_roll": {
                                    "pool": "common",
                                    "level": 15,
                                    "allowed_types": ["inventory"],
                                    "source": "backend_boss_final_roll",
                                },
                                "changes": [
                                    {
                                        "field": "inventory",
                                        "source": "boss_trophy",
                                        "item": {"name": "Сердечный трофей", "level": 24},
                                        "reason": "Трофей босса",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        )
        character = game.get_character_for_player(self.conn, self.telegram_id)
        names = [item["name"] for item in from_json(character["inventory_json"], [])]
        self.assertIn("Сердечный трофей", names)


if __name__ == "__main__":
    unittest.main()
