import sqlite3
import unittest

from aventura_bot.db import init_db
from aventura_bot.services import game
from aventura_bot.services.turn_files import validate_turn_append_payload, validate_turn_payload


class FixedChoiceRng:
    def __init__(self, index=0, random_value=0.0):
        self.index = index
        self.random_value = random_value

    def choice(self, seq):
        return seq[self.index % len(seq)]

    def random(self):
        return self.random_value


def sample_character(**overrides):
    character = {
        "id": 1,
        "name": "Рион",
        "race": "человек",
        "level": 5,
        "stats": {
            "сила": 8,
            "ловкость": 6,
            "интеллект": 4,
            "харизма": 3,
            "восприятие": 5,
            "удача": 4,
        },
        "inventory": [{"name": "Клинок", "level": 4}],
        "spells": [{"name": "Огненная стрела", "level": 3}],
        "pets": [{"name": "Ищейка", "level": 2}],
        "companions": [{"name": "Мира", "level": 5}],
        "mounts": [{"name": "Тихоступ", "level": 5}],
    }
    character.update(overrides)
    return character


def _mission(title, mission_type="standard", max_participants=None):
    mission = {
        "title": title,
        "type": mission_type,
        "description": "Описание миссии с ясной задачей для героев.",
        "difficulty": 6,
    }
    if max_participants is not None:
        mission["max_participants"] = max_participants
    return mission


class DeadlyTrialTests(unittest.TestCase):
    def test_difficulty_is_ceil_max_difficulty_times_1_2(self):
        self.assertEqual(game.deadly_trial_difficulty(10), 12)
        self.assertEqual(game.deadly_trial_difficulty(11), 14)

    def test_reward_level_modifier_has_strong_deadly_floor(self):
        self.assertEqual(game.deadly_trial_reward_level(1), 8)
        self.assertEqual(game.deadly_trial_reward_level(4), 8)
        self.assertEqual(game.deadly_trial_reward_level(6, mission_difficulty=18), 11)

    def test_deadly_trial_reward_validation_uses_strong_floor(self):
        mission = {"mission_type": "deadly_trial", "difficulty": 18}
        game._validate_reward_level_for_mission(11, mission, "inventory")
        with self.assertRaises(ValueError):
            game._validate_reward_level_for_mission(10, mission, "inventory")

    def test_ghost_stat_redistribution_preserves_total_stat_sum(self):
        character = sample_character()
        old_total = sum(character["stats"].values())
        transformed = game.ghost_character_state(character)
        self.assertEqual(transformed["race"], "призрак")
        self.assertEqual(transformed["stats"]["сила"], 1)
        self.assertEqual(transformed["stats"]["ловкость"], 1)
        self.assertEqual(sum(transformed["stats"].values()), old_total)

    def test_skeleton_stat_redistribution_preserves_total_stat_sum(self):
        character = sample_character()
        old_total = sum(character["stats"].values())
        transformed = game.skeleton_character_state(character)
        self.assertEqual(transformed["race"], "скелет")
        self.assertEqual(transformed["stats"]["интеллект"], 1)
        self.assertEqual(transformed["stats"]["харизма"], 1)
        self.assertEqual(sum(transformed["stats"].values()), old_total)

    def test_ghost_ignores_inventory_in_score(self):
        character = sample_character(race="призрак")
        score = game.calculate_hero_score(
            character,
            "интеллект",
            used_assets=[
                {"type": "inventory", "name": "Клинок", "level": 4},
                {"type": "spells", "name": "Огненная стрела", "level": 3},
            ],
        )
        self.assertEqual(score, 5 + 4 + 3)

    def test_skeleton_ignores_spells_in_score(self):
        character = sample_character(race="скелет")
        score = game.calculate_hero_score(
            character,
            "сила",
            used_assets=[
                {"type": "inventory", "name": "Клинок", "level": 4},
                {"type": "spells", "name": "Огненная стрела", "level": 3},
            ],
        )
        self.assertEqual(score, 5 + 8 + 4)

    def test_reincarnation_stat_pool_equals_old_total_stat_sum(self):
        character = sample_character()
        self.assertEqual(game.reincarnation_stat_pool(character), sum(character["stats"].values()))

    def test_reincarnation_legacy_selects_highest_level_asset(self):
        character = sample_character(
            inventory=[{"name": "Клинок", "level": 4}],
            spells=[{"name": "Огненная стрела", "level": 8}],
            pets=[{"name": "Ищейка", "level": 2}],
            companions=[],
            mounts=[],
        )
        legacy = game.select_reincarnation_legacy_asset(character, FixedChoiceRng())
        self.assertEqual(legacy["legacy_type"], "spells")
        self.assertEqual(legacy["legacy_level"], 8)
        self.assertEqual(legacy["source_name"], "Огненная стрела")

    def test_tied_legacy_candidates_are_randomized(self):
        character = sample_character(
            inventory=[{"name": "Клинок", "level": 5}],
            spells=[{"name": "Огненная стрела", "level": 5}],
            pets=[],
            companions=[],
            mounts=[],
        )
        legacy = game.select_reincarnation_legacy_asset(character, FixedChoiceRng(index=1))
        self.assertEqual(legacy["source_name"], "Огненная стрела")

    def test_old_name_is_locked(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        game.upsert_player(conn, 100, "old")
        game.upsert_player(conn, 200, "new")
        game.create_character(
            conn,
            100,
            "Рион",
            "мужской",
            "человек",
            "Молодой авантюрист с серым плащом и привычкой замечать опасные детали.",
            sample_character()["stats"],
            "Огненная стрела",
            ["кинжал", "плащ", "мел"],
        )
        with self.assertRaises(ValueError):
            game._validate_character_name_available(conn, 200, "Рион")

    def test_titled_rewards_appear_only_in_deadly_trial(self):
        reward = {
            "allowed_types": ["pet", "companion"],
        }
        game._maybe_apply_titled_reward(reward, True, FixedChoiceRng(random_value=0.1))
        self.assertEqual(reward["titled_reward"]["exclusive"], "deadly_trial")

        standard_reward = {
            "allowed_types": ["pet", "companion"],
        }
        game._maybe_apply_titled_reward(standard_reward, False, FixedChoiceRng(random_value=0.1))
        self.assertNotIn("titled_reward", standard_reward)

        with self.assertRaises(ValueError):
            game._validate_titled_reward_exclusivity(
                {"mission_type": "standard", "difficulty": 5},
                {
                    "field": "pet",
                    "pet": {
                        "name": "Король Ночи",
                        "level": 4,
                        "rank": "titled",
                        "exclusive": "deadly_trial",
                    },
                },
            )

    def test_deadly_trial_does_not_count_toward_minimum_turn_missions(self):
        payload = {
            "turn": {"title": "Ход риска"},
            "missions": [
                _mission("Обычная 1"),
                _mission("Обычная 2"),
                _mission("Испытание", mission_type="deadly_trial", max_participants=3),
            ],
        }
        with self.assertRaisesRegex(ValueError, "без учета deadly_trial"):
            validate_turn_payload(payload)

    def test_deadly_trial_can_be_added_as_append_outside_limit(self):
        payload = {
            "append_open_turn": True,
            "missions": [
                _mission("Испытание", mission_type="deadly_trial", max_participants=3),
            ],
        }
        validate_turn_append_payload(payload)

    def test_phased_boss_can_exceed_standard_difficulty_range(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        game.upsert_player(conn, 100, "hero")
        game.create_character(
            conn,
            100,
            "Рион",
            "мужской",
            "человек",
            "Молодой авантюрист с серым плащом и привычкой замечать опасные детали.",
            sample_character()["stats"],
            "Огненная стрела",
            ["кинжал", "плащ", "мел"],
        )

        boss = {
            "title": "Большой босс",
            "type": "boss",
            "subtype": "phased",
            "phase": 1,
            "max_phase": 2,
            "max_participants": 4,
            "difficulty": 30,
            "boss_name": "Большой босс",
            "continuation_key": "big_boss",
            "description": "Описание фазы босса.",
        }
        standard = _mission("Слишком сложная обычная миссия")
        standard["difficulty"] = boss["difficulty"]

        with self.assertRaisesRegex(ValueError, "Сложность миссии #1 должна быть"):
            game.validate_mission_additions_for_current_roster(conn, [standard])
        game.validate_mission_additions_for_current_roster(conn, [boss])


if __name__ == "__main__":
    unittest.main()
