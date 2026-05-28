import sqlite3
import unittest

from aventura_bot.db import from_json, init_db
from aventura_bot.services import game


class FreeActionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        game.upsert_player(self.conn, 7101, "free_player")
        self.character = game.create_character(
            self.conn,
            7101,
            "Боган",
            "мужской",
            "дварф",
            "Кузнец Авентуры, который любит проверять идеи в мастерской и спорить с городом на равных.",
            dict(game.DEFAULT_STATS),
            "Искра горна",
            ["Молот", "Фонарь", "Крюк"],
        )

    def _open_turn_with_mission(self) -> tuple[int, int]:
        turn_id = self.conn.execute(
            "INSERT INTO turns (title, status) VALUES ('Свободный день', 'open')"
        ).lastrowid
        mission_id = self.conn.execute(
            """
            INSERT INTO missions (turn_id, title, description, difficulty, status)
            VALUES (?, 'Доска заказов', 'Цели миссии: вернуть печать.', 8, 'open')
            """,
            (turn_id,),
        ).lastrowid
        self.conn.commit()
        return int(turn_id), int(mission_id)

    def test_free_action_replaces_regular_mission_choice_for_turn(self):
        turn_id, mission_id = self._open_turn_with_mission()
        game.join_mission(self.conn, 7101, mission_id)
        game.submit_action(
            self.conn,
            7101,
            "Боган идет к доске заказов, проверяет сорванные печати и пытается вернуть главную печать гильдии. "
            "Он сверяет следы на дереве, зовет писаря и закрепляет новую печать так, чтобы заказ снова приняли мастера.",
        )

        game.submit_free_action(
            self.conn,
            7101,
            "Боган идет в кузню и всю ночь придумывает крепление для маунта, чтобы тяжелый груз не бил по бокам. "
            "Он греет железо, спорит с подмастерьем и примеряет ремни к старому седлу, пока не находит рабочий угол.",
        )

        self.assertIsNotNone(game.current_free_action_for_player(self.conn, 7101))
        action_row = self.conn.execute("SELECT 1 FROM actions WHERE turn_id = ?", (turn_id,)).fetchone()
        participant_row = self.conn.execute(
            "SELECT 1 FROM mission_participants WHERE mission_id = ? AND character_id = ?",
            (mission_id, self.character["id"]),
        ).fetchone()
        self.assertIsNone(action_row)
        self.assertIsNone(participant_row)

    def test_free_action_is_exported_and_result_can_reward_player(self):
        turn_id, _mission_id = self._open_turn_with_mission()
        game.submit_free_action(
            self.conn,
            7101,
            "Боган идет в кузню и пытается улучшить свой крюк, используя Искру горна и старый молот. "
            "Он хочет сделать вещь не красивой, а надежной: чтобы крюк держал груз, не рвал ремень и не мешал маунту идти.",
        )

        export = game.build_turn_export(self.conn, turn_id)
        self.assertEqual(export["free_actions"][0]["name"], "Боган")
        self.assertEqual(export["free_actions"][0]["reward_roll"]["source"], "backend_free_action_roll")

        reward_level = int(export["free_actions"][0]["reward_roll"]["level"])
        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "free_action_results": [
                    {
                        "public_summary": "Боган провел ночь в кузне.",
                        "public_overview": "В кузне Авентуры стало жарче: Боган испытал новый крюк и оставил мастерам рабочий чертеж.",
                        "player_results": [
                            {
                                "character_id": self.character["id"],
                                "message": "Крюк вышел грубым, но надежным.",
                                "check": {
                                    "stat": "интеллект",
                                    "intention": "изобрести улучшение",
                                    "tone": "сосредоточенный ремесленный ход",
                                    "quality_tier": 3,
                                    "used_assets": [{"type": "inventory", "name": "Молот", "level": 1}],
                                },
                                "reward_roll": export["free_actions"][0]["reward_roll"],
                                "changes": [
                                    {"field": "level", "delta": 2, "reason": "Сильный свободный ход"},
                                    {
                                        "field": "inventory",
                                        "item": {"name": "Чертеж грузового крюка", "level": reward_level},
                                        "reason": "Результат изобретения",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
        )

        updated = game.get_character_for_player(self.conn, 7101)
        self.assertEqual(updated["level"], 3)
        names = [item["name"] for item in from_json(updated["inventory_json"], [])]
        self.assertIn("Чертеж грузового крюка", names)

    def test_free_action_lore_reference_adds_reward_bonus(self):
        turn_id, _mission_id = self._open_turn_with_mission()
        game.submit_free_action(
            self.conn,
            7101,
            "Боган идет в Каррок Манор и просит старые стены подсказать, где Авентура раньше хранила чертежи. "
            "Он не просто ищет тайник: он сверяет трещины, слушает сквозняки и уважительно обращается к дому как к союзнику.",
        )

        export = game.build_turn_export(self.conn, turn_id)
        reward_roll = export["free_actions"][0]["reward_roll"]

        self.assertTrue(reward_roll["lore_reference_bonus"])
        self.assertIn("Каррок Манор", reward_roll["lore_matches"])
        self.assertEqual(reward_roll["rare_chance"], game.FREE_ACTION_LORE_RARE_REWARD_CHANCE)
        self.assertEqual(reward_roll["level"], reward_roll["base_level"] + game.FREE_ACTION_LORE_LEVEL_BONUS)

    def test_split_free_action_scenes_are_merged_for_one_turn_result(self):
        game.upsert_player(self.conn, 7102, "free_friend")
        friend = game.create_character(
            self.conn,
            7102,
            "Зельда",
            "женский",
            "человек",
            "Городская исследовательница, которая ищет странные книги и редкие слухи.",
            dict(game.DEFAULT_STATS),
            "Пыльная карта",
            ["Книга", "Компас", "Свеча"],
        )
        turn_id, _mission_id = self._open_turn_with_mission()
        game.submit_free_action(
            self.conn,
            7101,
            "Боган идет к кузнецам и просит показать старые формы для замков. Он хочет понять, как сделать запор, "
            "который выдержит удар и при этом не заклинит от грязи после дождя.",
        )
        game.submit_free_action(
            self.conn,
            7102,
            "Зельда идет в городскую библиотеку и ищет карту старых подземных ходов. Она сравнивает полки, "
            "спрашивает архивариуса и отмечает места, где чернила выцвели слишком ровно.",
        )

        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "free_action_results": [
                    {
                        "public_summary": "Боган провел день в кузне.",
                        "public_overview": "У кузнецов появился новый разговор о надежных замках.",
                        "player_results": [
                            {
                                "character_id": self.character["id"],
                                "message": "Замок получился не изящным, но рабочим.",
                                "check": {"stat": "интеллект", "quality_tier": 2, "used_assets": []},
                                "changes": [{"field": "level", "delta": 1, "reason": "Полезный свободный ход"}],
                            }
                        ],
                    },
                    {
                        "public_summary": "Зельда нашла странную карту.",
                        "public_overview": "В библиотеке снова заговорили о подземных ходах под рынком.",
                        "player_results": [
                            {
                                "character_id": friend["id"],
                                "message": "Карта дала новую зацепку.",
                                "check": {"stat": "восприятие", "quality_tier": 2, "used_assets": []},
                                "changes": [{"field": "level", "delta": 1, "reason": "Полезный свободный ход"}],
                            }
                        ],
                    },
                ],
            },
        )

        stored = self.conn.execute("SELECT result_json FROM free_action_results WHERE turn_id = ?", (turn_id,)).fetchone()
        result = from_json(stored["result_json"], {})
        self.assertEqual(len(result["player_results"]), 2)
        self.assertIn("Боган провел день", result["public_summary"])
        self.assertIn("Зельда нашла", result["public_summary"])

    def test_unresolved_board_mission_carries_to_next_turn(self):
        old_turn_id, old_mission_id = self._open_turn_with_mission()
        game.close_turn(self.conn, old_turn_id)

        payload = {
            "turn": {"title": "Новый день"},
            "missions": [
                {"title": "Новая просьба", "description": "Цели миссии: помочь лавке.", "difficulty": 7},
                {"title": "Ночной шум", "description": "Цели миссии: проверить крышу.", "difficulty": 8},
                {"title": "Старый спор", "description": "Цели миссии: примирить мастеров.", "difficulty": 9},
            ],
        }
        new_turn_id = game.create_turn_from_payload(self.conn, payload)
        missions = self.conn.execute(
            "SELECT title FROM missions WHERE turn_id = ? ORDER BY id",
            (new_turn_id,),
        ).fetchall()

        self.assertIn("Доска заказов", [row["title"] for row in missions])
        source = self.conn.execute("SELECT carried_to_mission_id FROM missions WHERE id = ?", (old_mission_id,)).fetchone()
        self.assertGreater(int(source["carried_to_mission_id"]), 0)


if __name__ == "__main__":
    unittest.main()
