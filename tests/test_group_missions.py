import sqlite3
import unittest

from aventura_bot.db import from_json, init_db
from aventura_bot.services import game


class GroupMissionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        self.characters = []
        for index in range(3):
            telegram_id = 9000 + index
            game.upsert_player(self.conn, telegram_id, f"group_{index}")
            character = game.create_character(
                self.conn,
                telegram_id,
                f"Герой {index}",
                "женский",
                "человек",
                "Участница отряда Авентуры, готовая действовать вместе с другими героями.",
                dict(game.DEFAULT_STATS),
                f"Щит {index}",
                [f"Клинок {index}", f"Фонарь {index}", f"Веревка {index}"],
            )
            self.characters.append(character)

    def _mission(
        self,
        difficulty: int,
        mission_type: str = "standard",
        participant_count: int = 1,
    ) -> tuple[int, int]:
        turn_id = self.conn.execute(
            "INSERT INTO turns (title, status) VALUES ('Групповой ход', 'open')"
        ).lastrowid
        mission_id = self.conn.execute(
            """
            INSERT INTO missions (turn_id, title, description, mission_type, difficulty, status)
            VALUES (?, 'Общий рубеж', 'Цели миссии: удержать мост.', ?, ?, 'open')
            """,
            (turn_id, mission_type, difficulty),
        ).lastrowid
        for character in self.characters[:participant_count]:
            self.conn.execute(
                "INSERT INTO mission_participants (mission_id, character_id) VALUES (?, ?)",
                (mission_id, character["id"]),
            )
            self.conn.execute(
                """
                INSERT INTO actions (turn_id, mission_id, character_id, action_text)
                VALUES (?, ?, ?, ?)
                """,
                (
                    turn_id,
                    mission_id,
                    character["id"],
                    "Герой идет к цели миссии, действует по ситуации и помогает удержать общий рубеж.",
                ),
            )
        self.conn.commit()
        return int(turn_id), int(mission_id)

    def test_difficulty_range_uses_roster_quartiles(self):
        ratings = game.character_power_ratings(self.conn)
        lower_quartile = game._roster_percentile(ratings, 0.25)
        upper_quartile = game._roster_percentile(ratings, 0.75)
        self.assertEqual(
            game.mission_difficulty_bounds(self.conn),
            (
                game._round_half_up(lower_quartile * game.LOW_MISSION_DIFFICULTY_MULTIPLIER),
                game._round_half_up(upper_quartile * game.HIGH_MISSION_DIFFICULTY_MULTIPLIER),
            ),
        )

    def test_logic_signals_have_short_recognizable_scale(self):
        self.assertEqual(game.logic_tier_from_signals({"goal": False, "method": True, "scene": True}), 0)
        self.assertEqual(game.logic_tier_from_signals({"goal": True, "method": False, "scene": False}), 1)
        self.assertEqual(game.logic_tier_from_signals({"goal": True, "method": True, "scene": False}), 2)
        self.assertEqual(game.logic_tier_from_signals({"goal": True, "method": True, "scene": True}), 3)
        self.assertEqual(game.personal_contribution(20, 3, core_score=10), 25)
        self.assertEqual(game.personal_contribution(10, 3, core_score=5), 13)

    def test_multiple_assets_have_diminishing_contribution(self):
        character = self.characters[0]
        self.assertEqual(
            game.calculate_hero_score(
                character,
                "сила",
                used_assets=[
                    {"type": "inventory", "name": "Клинок", "level": 20},
                    {"type": "spells", "name": "Щит", "level": 10},
                    {"type": "pet", "name": "Ищейка", "level": 8},
                    {"type": "companion", "name": "Проводник", "level": 6},
                ],
            ),
            1 + 5 + 20 + 5 + 2 + 1,
        )

    def test_export_caps_reward_scale_by_personal_readiness(self):
        turn_id, _mission_id = self._mission(30)
        self.conn.execute(
            """
            INSERT INTO npc_reputations (character_id, npc_key, npc_name, reputation)
            VALUES (?, 'mira_belozlatka', 'Сержант Мира Белозлатка', 11)
            """,
            (self.characters[0]["id"],),
        )
        self.conn.commit()
        payload = game.build_turn_export(self.conn, turn_id)
        mission = payload["missions"][0]

        self.assertEqual(mission["participants"][0]["reward_roll"]["reward_difficulty"], 8)
        self.assertEqual(mission["participants"][0]["npc_reputations"][0]["reputation"], 11)
        self.assertEqual(mission["resolution"]["mode"], "group_total")
        self.assertEqual(mission["resolution"]["critical_success_threshold"], 36)

    def test_successful_npc_mission_can_raise_reputation(self):
        turn_id, mission_id = self._mission(6)
        character = self.characters[0]

        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [
                    {
                        "mission_id": mission_id,
                        "status": "success",
                        "player_results": [
                            {
                                "character_id": character["id"],
                                "check": {
                                    "success": True,
                                    "stat": "харизма",
                                    "core_score": 6,
                                    "base_score": 6,
                                    "logic_signals": {"goal": True, "method": True, "scene": False},
                                    "logic_tier": 2,
                                    "personal_contribution": 6,
                                    "mission_total": 6,
                                },
                                "changes": [
                                    {
                                        "field": "npc_reputation",
                                        "npc_key": "mira_belozlatka",
                                        "npc_name": "Сержант Мира Белозлатка",
                                        "delta": 4,
                                        "reason": "Герой помог миссии Миры.",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        )

        reputations = game.list_npc_reputations(self.conn, character["id"])
        self.assertEqual(reputations[0]["npc_key"], "mira_belozlatka")
        self.assertEqual(reputations[0]["reputation"], 4)

    def test_failed_npc_mission_cannot_raise_reputation(self):
        turn_id, mission_id = self._mission(7)
        character = self.characters[0]

        with self.assertRaisesRegex(ValueError, "только при успешном выполнении"):
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
                                    "character_id": character["id"],
                                    "check": {
                                        "success": False,
                                        "stat": "харизма",
                                        "core_score": 6,
                                        "base_score": 6,
                                        "logic_signals": {"goal": True, "method": False, "scene": False},
                                        "logic_tier": 1,
                                        "personal_contribution": 3,
                                        "mission_total": 3,
                                    },
                                    "changes": [
                                        {
                                            "field": "npc_reputation",
                                            "npc_key": "mira_belozlatka",
                                            "npc_name": "Сержант Мира Белозлатка",
                                            "delta": 2,
                                            "reason": "Провал не должен повышать репутацию.",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            )

    def test_npc_mission_reputation_gain_uses_slow_cap(self):
        turn_id, mission_id = self._mission(6)
        character = self.characters[0]

        with self.assertRaisesRegex(ValueError, "максимум"):
            game.apply_result_payload(
                self.conn,
                {
                    "turn_id": turn_id,
                    "mission_results": [
                        {
                            "mission_id": mission_id,
                            "status": "success",
                            "player_results": [
                                {
                                    "character_id": character["id"],
                                    "check": {
                                        "success": True,
                                        "stat": "харизма",
                                        "core_score": 6,
                                        "base_score": 6,
                                        "logic_signals": {"goal": True, "method": True, "scene": False},
                                        "logic_tier": 2,
                                        "personal_contribution": 6,
                                        "mission_total": 6,
                                    },
                                    "changes": [
                                        {
                                            "field": "npc_reputation",
                                            "npc_key": "mira_belozlatka",
                                            "npc_name": "Сержант Мира Белозлатка",
                                            "delta": 10,
                                            "reason": "Слишком быстрый рост.",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            )

    def test_group_total_resolves_standard_mission_success(self):
        turn_id, mission_id = self._mission(12, participant_count=2)
        results = []
        for index, character in enumerate(self.characters[:2]):
            changes = [{"field": "level", "delta": 2, "reason": "Полноценный вклад"}]
            result = {
                "character_id": character["id"],
                "check": {
                    "success": True,
                    "stat": "сила",
                    "core_score": 6,
                    "base_score": 6,
                    "logic_signals": {"goal": True, "method": True, "scene": False},
                    "logic_tier": 2,
                    "personal_contribution": 6,
                    "mission_total": 12,
                },
                "changes": changes,
            }
            if index == 0:
                result["reward_roll"] = {"level": 2, "allowed_types": ["inventory"]}
                changes.append(
                    {"field": "inventory", "item": {"name": "Ключ моста", "level": 2}, "reason": "Победа"}
                )
            results.append(result)
        game.apply_result_payload(
            self.conn,
            {"turn_id": turn_id, "mission_results": [{"mission_id": mission_id, "status": "success", "player_results": results}]},
        )
        stored = self.conn.execute("SELECT status FROM missions WHERE id = ?", (mission_id,)).fetchone()
        self.assertEqual(stored["status"], "completed")

    def test_critical_success_improves_strong_reward(self):
        turn_id, mission_id = self._mission(7)
        character = self.characters[0]
        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [
                    {
                        "mission_id": mission_id,
                        "status": "critical_success",
                        "player_results": [
                            {
                                "character_id": character["id"],
                                "check": {
                                    "success": True,
                                    "stat": "сила",
                                    "core_score": 6,
                                    "base_score": 6,
                                    "logic_signals": {"goal": True, "method": True, "scene": True},
                                    "logic_tier": 3,
                                    "personal_contribution": 9,
                                    "mission_total": 9,
                                },
                                "reward_roll": {"level": 4, "allowed_types": ["inventory"]},
                                "changes": [
                                    {"field": "level", "delta": 2, "reason": "Сильный вклад"},
                                    {"field": "inventory", "item": {"name": "Знак рубежа", "level": 5}, "reason": "Критический успех"},
                                ],
                            }
                        ],
                    }
                ],
            },
        )
        character_after = game.get_character_for_player(self.conn, 9000)
        items = from_json(character_after["inventory_json"], [])
        self.assertIn("Знак рубежа", [item["name"] for item in items])

    def test_teamwork_bonus_can_lift_coordinated_group_to_critical_success(self):
        turn_id, mission_id = self._mission(13, participant_count=2)
        results = []
        for character in self.characters[:2]:
            results.append(
                {
                    "character_id": character["id"],
                    "check": {
                        "success": True,
                        "stat": "сила",
                        "core_score": 6,
                        "base_score": 6,
                        "logic_signals": {"goal": True, "method": True, "scene": True},
                        "logic_tier": 3,
                        "personal_contribution": 9,
                        "mission_total": 23,
                    },
                    "reward_roll": {"level": 2, "allowed_types": ["inventory"]},
                    "changes": [
                        {"field": "level", "delta": 2, "reason": "Сильный вклад"},
                        {"field": "inventory", "item": {"name": f"Знак команды {character['id']}", "level": 3}},
                    ],
                }
            )

        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [
                    {
                        "mission_id": mission_id,
                        "status": "critical_success",
                        "teamwork_bonus": {"value": 5, "reason": "Оба героя полностью скоординировались."},
                        "player_results": results,
                    }
                ],
            },
        )
        stored = self.conn.execute("SELECT status FROM missions WHERE id = ?", (mission_id,)).fetchone()
        self.assertEqual(stored["status"], "completed")

    def test_critical_success_allows_marked_rare_upgrade(self):
        turn_id, mission_id = self._mission(7)
        character = self.characters[0]
        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [
                    {
                        "mission_id": mission_id,
                        "status": "critical_success",
                        "player_results": [
                            {
                                "character_id": character["id"],
                                "check": {
                                    "success": True,
                                    "stat": "сила",
                                    "core_score": 6,
                                    "base_score": 6,
                                    "logic_signals": {"goal": True, "method": True, "scene": True},
                                    "logic_tier": 3,
                                    "personal_contribution": 9,
                                    "mission_total": 9,
                                },
                                "reward_roll": {
                                    "level": 4,
                                    "allowed_types": ["inventory", "spells", "gold", "stat"],
                                    "critical_success_rare_upgrade_allowed_types": [
                                        "inventory",
                                        "spells",
                                        "stat",
                                        "pet",
                                        "companion",
                                        "mount",
                                    ],
                                },
                                "changes": [
                                    {"field": "level", "delta": 2, "reason": "Сильный вклад"},
                                    {
                                        "field": "pet",
                                        "source": "critical_rare_upgrade",
                                        "pet": {"name": "Мостовой Сторож", "level": 5},
                                        "reason": "Критический редкий апгрейд",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
        )
        character_after = game.get_character_for_player(self.conn, 9000)
        pets = from_json(character_after["pets_json"], [])
        self.assertIn("Мостовой Сторож", [pet["name"] for pet in pets])

    def test_rare_upgrade_requires_critical_marker(self):
        turn_id, mission_id = self._mission(7)
        character = self.characters[0]
        with self.assertRaisesRegex(ValueError, "allowed_types"):
            game.apply_result_payload(
                self.conn,
                {
                    "turn_id": turn_id,
                    "mission_results": [
                        {
                            "mission_id": mission_id,
                            "status": "critical_success",
                            "player_results": [
                                {
                                    "character_id": character["id"],
                                    "check": {
                                        "success": True,
                                        "stat": "сила",
                                        "core_score": 6,
                                        "base_score": 6,
                                        "logic_signals": {"goal": True, "method": True, "scene": True},
                                        "logic_tier": 3,
                                        "personal_contribution": 9,
                                        "mission_total": 9,
                                    },
                                    "reward_roll": {"level": 4, "allowed_types": ["inventory"]},
                                    "changes": [
                                        {"field": "level", "delta": 2, "reason": "Сильный вклад"},
                                        {"field": "pet", "pet": {"name": "Мостовой Сторож", "level": 5}},
                                    ],
                                }
                            ],
                        }
                    ],
                },
            )

    def test_transferred_asset_scores_for_receiver_and_cools_down_for_owner(self):
        turn_id, mission_id = self._mission(13, participant_count=2)
        transferred = {"type": "inventory", "name": "Клинок 0", "level": 1}
        game.apply_result_payload(
            self.conn,
            {
                "turn_id": turn_id,
                "mission_results": [
                    {
                        "mission_id": mission_id,
                        "status": "success",
                        "player_results": [
                            {
                                "character_id": self.characters[0]["id"],
                                "check": {
                                    "stat": "сила",
                                    "core_score": 6,
                                    "base_score": 6,
                                    "logic_signals": {"goal": True, "method": True, "scene": False},
                                    "logic_tier": 2,
                                    "personal_contribution": 6,
                                    "mission_total": 13,
                                    "success": True,
                                    "used_assets": [transferred],
                                    "transferred_assets": [transferred],
                                    "received_assets": [],
                                },
                                "changes": [{"field": "level", "delta": 2, "reason": "Поддержка союзника"}],
                            },
                            {
                                "character_id": self.characters[1]["id"],
                                "check": {
                                    "stat": "сила",
                                    "core_score": 6,
                                    "base_score": 7,
                                    "logic_signals": {"goal": True, "method": True, "scene": False},
                                    "logic_tier": 2,
                                    "personal_contribution": 7,
                                    "mission_total": 13,
                                    "success": True,
                                    "used_assets": [],
                                    "transferred_assets": [],
                                    "received_assets": [transferred],
                                },
                                "changes": [{"field": "level", "delta": 2, "reason": "Полученная помощь"}],
                            },
                        ],
                    }
                ],
            },
        )
        owner = game.get_character_for_player(self.conn, 9000)
        items = from_json(owner["inventory_json"], [])
        sword = next(item for item in items if item["name"] == "Клинок 0")
        self.assertEqual(sword["cooldown_until_turn"], turn_id + game.DEFAULT_ASSET_COOLDOWN_TURNS)

    def test_group_result_requires_every_participant_with_submitted_action(self):
        turn_id, mission_id = self._mission(10, participant_count=2)
        payload = {
            "turn_id": turn_id,
            "mission_results": [
                {
                    "mission_id": mission_id,
                    "status": "success",
                    "player_results": [
                        {
                            "character_id": self.characters[0]["id"],
                            "check": {
                                "success": True,
                                "stat": "сила",
                                "core_score": 6,
                                "base_score": 10,
                                "logic_signals": {"goal": True, "method": True, "scene": False},
                                "logic_tier": 2,
                                "personal_contribution": 10,
                                "mission_total": 10,
                            },
                            "changes": [{"field": "level", "delta": 2, "reason": "Полноценный вклад"}],
                        }
                    ],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "каждого участника"):
            game.apply_result_payload(self.conn, payload)

    def test_join_without_action_is_not_exported_or_required_for_result(self):
        turn_id, mission_id = self._mission(10, participant_count=1)
        self.conn.execute(
            "INSERT INTO mission_participants (mission_id, character_id) VALUES (?, ?)",
            (mission_id, self.characters[1]["id"]),
        )
        self.conn.commit()

        export = game.build_turn_export(self.conn, turn_id)
        self.assertEqual(
            [participant["character_id"] for participant in export["missions"][0]["participants"]],
            [self.characters[0]["id"]],
        )

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
                                "character_id": self.characters[0]["id"],
                                "check": {
                                    "success": True,
                                    "stat": "сила",
                                    "core_score": 6,
                                    "base_score": 6,
                                    "logic_signals": {"goal": True, "method": True, "scene": False},
                                    "logic_tier": 2,
                                    "personal_contribution": 6,
                                    "mission_total": 6,
                                },
                                "changes": [{"field": "level", "delta": 1, "reason": "Полноценный вклад"}],
                            }
                        ],
                    }
                ],
            },
        )

    def test_mission_slot_is_reserved_by_action_not_join(self):
        turn_id = self.conn.execute(
            "INSERT INTO turns (title, status) VALUES ('Лимит миссии', 'open')"
        ).lastrowid
        mission_id = self.conn.execute(
            """
            INSERT INTO missions (turn_id, title, description, difficulty, status, max_participants)
            VALUES (?, 'Один слот', 'Цели миссии: открыть дверь.', 6, 'open', 1)
            """,
            (turn_id,),
        ).lastrowid
        self.conn.commit()

        game.join_mission(self.conn, 9000, mission_id)
        game.join_mission(self.conn, 9001, mission_id)
        game.submit_action(
            self.conn,
            9000,
            "Герой подходит к двери, проверяет петли, слушает замок и пытается открыть ее без шума, "
            "чтобы выполнить цель миссии и не поднять тревогу в соседнем коридоре.",
        )

        with self.assertRaisesRegex(ValueError, "максимум участников с отправленным ходом"):
            game.submit_action(
                self.conn,
                9001,
                "Герой тоже подходит к двери и пытается открыть ее своим способом, аккуратно проверяя ручку, "
                "замочную скважину и щель у пола, но слот уже занят ходом другого героя.",
            )

    def test_passed_intermediate_boss_phase_keeps_two_level_reward(self):
        turn_id = self.conn.execute(
            "INSERT INTO turns (title, status) VALUES ('Фаза босса', 'open')"
        ).lastrowid
        mission_id = self.conn.execute(
            """
            INSERT INTO missions (
                turn_id, title, description, mission_type, mission_subtype,
                phase, max_phase, difficulty, status
            )
            VALUES (?, 'Первая фаза', 'Цель: разбить щит.', 'boss', 'phased', 1, 2, 6, 'open')
            """,
            (turn_id,),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO mission_participants (mission_id, character_id) VALUES (?, ?)",
            (mission_id, self.characters[0]["id"]),
        )
        self.conn.execute(
            """
            INSERT INTO actions (turn_id, mission_id, character_id, action_text)
            VALUES (?, ?, ?, 'Герой бьет по щиту босса и держит позицию.')
            """,
            (turn_id, mission_id, self.characters[0]["id"]),
        )
        self.conn.commit()

        game.apply_result_payload(
            self.conn,
            {
                "turn_id": int(turn_id),
                "mission_results": [
                    {
                        "mission_id": int(mission_id),
                        "status": "ongoing",
                        "player_results": [
                            {
                                "character_id": self.characters[0]["id"],
                                "check": {
                                    "success": True,
                                    "stat": "сила",
                                    "core_score": 6,
                                    "base_score": 6,
                                    "logic_signals": {"goal": True, "method": True, "scene": False},
                                    "logic_tier": 2,
                                    "personal_contribution": 6,
                                    "mission_total": 6,
                                },
                                "changes": [{"field": "level", "delta": 2, "reason": "Пройденная фаза"}],
                            }
                        ],
                    }
                ],
            },
        )
        character = game.get_character_for_player(self.conn, 9000)
        self.assertEqual(character["level"], 3)


if __name__ == "__main__":
    unittest.main()
