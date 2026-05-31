from __future__ import annotations

import math
import random
import re
import sqlite3
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from aventura_bot.db import from_json, row_to_dict, to_json

STAT_NAMES = ("сила", "ловкость", "интеллект", "харизма", "восприятие", "удача")
DEFAULT_STATS = {name: 5 for name in STAT_NAMES}
STAT_POINTS_TOTAL = 30
MISSION_MAX_PARTICIPANTS = 3
BOSS_MAX_PARTICIPANTS = 9
MISSION_TYPE_STANDARD = "standard"
MISSION_TYPE_BOSS = "boss"
MISSION_TYPE_DEADLY_TRIAL = "deadly_trial"
DEADLY_TRIAL_LABEL = "Смертельное испытание"
LOW_MISSION_DIFFICULTY_MULTIPLIER = 0.90
HIGH_MISSION_DIFFICULTY_MULTIPLIER = 2.60
DEADLY_TRIAL_DIFFICULTY_MULTIPLIER = 3.60
DEADLY_TRIAL_REWARD_LEVEL_BONUS = 3
DEADLY_TRIAL_MIN_REWARD_LEVEL = 4
DEADLY_TRIAL_MIN_REWARD_DIFFICULTY_RATIO = 0.60
DEADLY_TRIAL_ABSOLUTE_MIN_REWARD_LEVEL = 8
DEADLY_TRIAL_DEATH_THRESHOLD = 5
DEADLY_TRIAL_TITLED_REWARD_CHANCE = 0.30
DEADLY_TRIAL_TITLED_TYPES = ("pet", "familiar", "companion", "mount")
DEATH_OUTCOMES = ("ghost", "skeleton", "reincarnation")
MISSION_CRITICAL_SUCCESS_MULTIPLIER = 1.20
MISSION_TEAMWORK_BONUS = 5
MISSION_REWARD_PARTY_SHARE = MISSION_MAX_PARTICIPANTS
LOGIC_MULTIPLIERS = {0: "0", 1: "50% hero core", 2: "base score", 3: "base score + 50% hero core"}
ASSET_CONTRIBUTION_MULTIPLIERS = (1.0, 0.50, 0.25, 0.10, 0.10)
BOSS_FINAL_REWARD_DIVISOR = 4
BOSS_TROPHY_REWARD_DIVISOR = 3
BOSS_REWARD_VARIANCE = 0.20
BOSS_FINAL_REWARD_TYPES = ("inventory", "spells", "stat", "pet", "companion", "mount")
MIN_MISSIONS_PER_TURN = 3
STARTER_ITEM_COUNT = 3
CHARACTER_NAME_MAX_LENGTH = 60
CHARACTER_FIELD_MAX_LENGTH = 40
CHARACTER_DESCRIPTION_MIN_LENGTH = 40
CHARACTER_DESCRIPTION_MAX_LENGTH = 700
ASSET_NAME_MAX_LENGTH = 100
ACTION_TEXT_MIN_LENGTH = 120
ACTION_TEXT_MAX_LENGTH = 3000
RARE_REWARD_CHANCE = 0.10
MISSION_CRITICAL_RARE_UPGRADE_CHANCE = 0.25
DEADLY_TRIAL_CRITICAL_RARE_UPGRADE_CHANCE = 0.35
FREE_ACTION_RARE_REWARD_CHANCE = 0.15
FREE_ACTION_LORE_RARE_REWARD_CHANCE = 0.35
FREE_ACTION_LORE_LEVEL_BONUS = 1
GOLD_REWARD_MULTIPLIER = 3
COMMON_REWARD_TYPES = ("inventory", "spells", "gold", "stat")
RARE_REWARD_TYPES = ("inventory", "spells", "stat", "pet", "companion", "mount")
SHOP_BUY_PRICE_PER_LEVEL = 2
SHOP_SELL_PRICE_PER_LEVEL = 1
SHOP_SYSTEM_STOCK_SIZE = 12
DEFAULT_ASSET_COOLDOWN_TURNS = 2
TAVERN_LEVEL_PRICE_DIVISOR = 4
TAVERN_COOLDOWN_PRICE_DIVISOR = 4
CRAFT_RELATIONSHIP_MULTIPLIERS = {
    "weak": 0.25,
    "good": 0.50,
    "strong": 0.75,
}

SHOP_PREFIXES = (
    "Стальной",
    "Мифриловый",
    "Драконий",
    "Рунный",
    "Гномий",
    "Эльфийский",
    "Паладинский",
    "Ведьмачий",
    "Теневой",
    "Кровавый",
    "Лунный",
    "Инфернальный",
    "Гильдейский",
    "Каррокский",
    "Пороговый",
)

SHOP_BASE_ITEMS = (
    "меч бастард",
    "боевой топор",
    "длинный лук",
    "арбалет охотника",
    "кинжал дуэлянта",
    "копье стража",
    "молот храмовника",
    "кольчужная рубаха",
    "латы авантюриста",
    "кожаный доспех следопыта",
    "плащ ночного дозора",
    "мантия боевого мага",
    "сапоги дальнего пути",
    "перчатки взломщика",
    "пояс зельевара",
    "амулет защиты",
    "кольцо меткости",
    "щит башенной стражи",
    "рюкзак искателя",
    "набор походных инструментов",
)

SHOP_SUFFIXES = (
    "из арсенала Авентуры",
    "Каррок Манора",
    "Канцелярии Порогов",
    "из кузни Черных Лестниц",
    "с рынка Семи Вывесок",
    "для охоты на чудовищ",
    "для похода в руины",
    "с печатью гильдейского мастера",
    "с серебряной насечкой",
    "с драконьей заклепкой",
    "с руной стойкости",
    "с руной удачного удара",
)


def upsert_player(
    conn: sqlite3.Connection,
    telegram_id: int,
    username: str | None,
    notify_enabled: bool | None = None,
) -> dict[str, Any]:
    if notify_enabled is None:
        conn.execute(
            """
            INSERT INTO players (telegram_id, username)
            VALUES (?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username
            """,
            (telegram_id, username),
        )
    else:
        conn.execute(
            """
            INSERT INTO players (telegram_id, username, notify_enabled)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                notify_enabled = excluded.notify_enabled
            """,
            (telegram_id, username, int(notify_enabled)),
        )
    conn.commit()
    row = conn.execute("SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)).fetchone()
    return row_to_dict(row) or {}


def get_player(conn: sqlite3.Connection, telegram_id: int) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)).fetchone())


def list_player_telegram_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT telegram_id FROM players WHERE notify_enabled = 1 ORDER BY id").fetchall()
    return [int(row["telegram_id"]) for row in rows]


def get_character_for_player(conn: sqlite3.Connection, telegram_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT characters.*
        FROM characters
        JOIN players ON players.id = characters.player_id
        WHERE players.telegram_id = ?
          AND characters.is_active = 1
        ORDER BY characters.id DESC
        LIMIT 1
        """,
        (telegram_id,),
    ).fetchone()
    return row_to_dict(row)


def get_character_change_log(conn: sqlite3.Connection, telegram_id: int, limit: int = 10) -> list[dict[str, Any]]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        return []
    rows = conn.execute(
        """
        SELECT change_log.*, turns.title AS turn_title
        FROM change_log
        JOIN turns ON turns.id = change_log.turn_id
        WHERE change_log.character_id = ?
        ORDER BY change_log.id DESC
        LIMIT ?
        """,
        (character["id"], limit),
    ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def list_public_roster(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            characters.id,
            characters.name,
            characters.race,
            characters.description,
            characters.level,
            players.telegram_id,
            players.username
        FROM characters
        JOIN players ON players.id = characters.player_id
        WHERE players.notify_enabled = 1
          AND characters.is_active = 1
        ORDER BY characters.level DESC, characters.name COLLATE NOCASE ASC
        """
    ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def normalize_stats(stats: dict[str, int] | None, *, require_exact_total: bool = True) -> dict[str, int]:
    if stats is None:
        return dict(DEFAULT_STATS)

    normalized = {name: int(stats.get(name, 0)) for name in STAT_NAMES}
    missing = [name for name, value in normalized.items() if value <= 0]
    if missing:
        raise ValueError(f"Каждая характеристика должна быть не меньше 1. Проверь: {', '.join(missing)}.")

    total = sum(normalized.values())
    if require_exact_total and total != STAT_POINTS_TOTAL:
        raise ValueError(f"Сумма характеристик должна быть {STAT_POINTS_TOTAL}, сейчас {total}.")
    if not require_exact_total and total < STAT_POINTS_TOTAL:
        raise ValueError(f"Сумма характеристик восстановленного героя не должна быть меньше {STAT_POINTS_TOTAL}, сейчас {total}.")

    return normalized


def normalize_starter_spell(spell_name: str) -> list[dict[str, Any]]:
    spell_name = spell_name.strip()
    if not spell_name:
        raise ValueError("На старте у персонажа должно быть одно заклинание.")
    _validate_text_length(spell_name, "Название заклинания", 1, ASSET_NAME_MAX_LENGTH)
    return [{"name": spell_name, "level": 1}]


def normalize_starter_items(item_names: list[str]) -> list[dict[str, Any]]:
    cleaned = [name.strip() for name in item_names if name.strip()]
    if len(cleaned) != STARTER_ITEM_COUNT:
        raise ValueError(f"На старте должно быть ровно {STARTER_ITEM_COUNT} предмета.")
    for name in cleaned:
        _validate_text_length(name, "Название предмета", 1, ASSET_NAME_MAX_LENGTH)
    _validate_unique_names(cleaned)
    return [{"uid": _new_item_uid(), "name": name, "level": 1} for name in cleaned]


def normalize_leveled_entity(name: str | None) -> dict[str, Any] | None:
    if name is None or not name.strip():
        return None
    return {"name": name.strip(), "level": 1}


def _new_item_uid() -> str:
    return uuid.uuid4().hex[:10]


def character_level_bounds(conn: sqlite3.Connection) -> tuple[int, int] | None:
    row = conn.execute("SELECT MIN(level) AS min_level, MAX(level) AS max_level FROM characters WHERE is_active = 1").fetchone()
    if row is None or row["min_level"] is None or row["max_level"] is None:
        return None
    return int(row["min_level"]), int(row["max_level"])


def mission_difficulty_bounds(conn: sqlite3.Connection) -> tuple[int, int] | None:
    ratings = character_power_ratings(conn, _cooldown_reference_turn_id(conn))
    if not ratings:
        return None
    lower_quartile = _roster_percentile(ratings, 0.25)
    upper_quartile = _roster_percentile(ratings, 0.75)
    return (
        max(1, _round_half_up(lower_quartile * LOW_MISSION_DIFFICULTY_MULTIPLIER)),
        max(1, _round_half_up(upper_quartile * HIGH_MISSION_DIFFICULTY_MULTIPLIER)),
    )


def character_power_ratings(conn: sqlite3.Connection, turn_id: int | None = None) -> list[int]:
    rows = conn.execute("SELECT * FROM characters WHERE is_active = 1 ORDER BY id").fetchall()
    return [character_power_rating(row_to_dict(row) or {}, turn_id) for row in rows]


def character_power_rating(character: dict[str, Any], turn_id: int | None = None) -> int:
    stats = from_json(character.get("stats_json"), DEFAULT_STATS)
    best_stat = max((int(value) for value in stats.values()), default=0)
    inventory = from_json(character.get("inventory_json"), [])
    spells = from_json(character.get("spells_json"), [])
    pets = _entity_list(character, "pet_json", "pets_json")
    companions = _entity_list(character, "companion_json", "companions_json")
    mounts = _entity_list(character, "mount_json", "mounts_json")
    race = str(character.get("race") or "").strip().casefold()
    if race == "призрак":
        inventory = []
    if race == "скелет":
        spells = []
    collections = (inventory, spells, pets, companions, mounts)
    best_assets = [_best_level([asset for asset in assets if asset_is_active(asset, turn_id)]) for assets in collections]
    return int(character.get("level", 1)) + best_stat + _diminished_asset_score(best_assets)


def deadly_trial_difficulty(upper_quartile_power: int) -> int:
    return max(1, _round_half_up(int(upper_quartile_power) * DEADLY_TRIAL_DIFFICULTY_MULTIPLIER))


def party_difficulty_ceiling(conn: sqlite3.Connection, max_participants: int) -> int | None:
    ratings = character_power_ratings(conn, _cooldown_reference_turn_id(conn))
    if not ratings:
        return None
    return sum(sorted(ratings, reverse=True)[:max(1, int(max_participants))]) + 2


def _round_half_up(value: float) -> int:
    return math.floor(float(value) + 0.5)


def _roster_percentile(ratings: list[int], percentile: float) -> int:
    ordered = sorted(int(rating) for rating in ratings)
    index = math.floor((len(ordered) - 1) * percentile)
    return ordered[index]


def _upper_quartile_power(conn: sqlite3.Connection) -> int | None:
    ratings = character_power_ratings(conn, _cooldown_reference_turn_id(conn))
    if not ratings:
        return None
    return _roster_percentile(ratings, 0.75)


def _diminished_asset_score(levels: list[int]) -> int:
    ordered = sorted((max(0, int(level)) for level in levels), reverse=True)
    return sum(
        math.ceil(level * multiplier)
        for level, multiplier in zip(ordered, ASSET_CONTRIBUTION_MULTIPLIERS)
    )


def personal_difficulty_share(mission_difficulty: int) -> int:
    return max(1, math.ceil(int(mission_difficulty) / MISSION_REWARD_PARTY_SHARE))


def deadly_trial_personal_danger_threshold(mission_difficulty: int) -> int:
    return personal_difficulty_share(mission_difficulty)


def deadly_trial_reward_level(base_reward_level: int, mission_difficulty: int | None = None) -> int:
    difficulty_floor = 0
    if mission_difficulty is not None:
        difficulty_floor = math.ceil(personal_difficulty_share(mission_difficulty) * DEADLY_TRIAL_MIN_REWARD_DIFFICULTY_RATIO)
    return max(
        int(base_reward_level) + DEADLY_TRIAL_REWARD_LEVEL_BONUS,
        DEADLY_TRIAL_MIN_REWARD_LEVEL,
        DEADLY_TRIAL_ABSOLUTE_MIN_REWARD_LEVEL,
        difficulty_floor,
    )


def mission_type_label(mission_type: Any) -> str:
    normalized = _normalize_mission_type(mission_type)
    if normalized == MISSION_TYPE_DEADLY_TRIAL:
        return DEADLY_TRIAL_LABEL
    if normalized == MISSION_TYPE_BOSS:
        return "Босс-миссия"
    return "Обычная миссия"


def mission_is_deadly_trial(mission: dict[str, Any]) -> bool:
    return _normalize_mission_type(mission.get("mission_type") or mission.get("type")) == MISSION_TYPE_DEADLY_TRIAL


def mission_difficulty_label(
    difficulty: int,
    bounds: tuple[int, int] | None = None,
    mission_type: Any = None,
) -> str:
    if _normalize_mission_type(mission_type) == MISSION_TYPE_DEADLY_TRIAL:
        return "Смертельно"
    value = int(difficulty)
    if bounds is None:
        if value <= 6:
            return "Легко"
        if value <= 10:
            return "Посильно"
        if value <= 16:
            return "Сложно"
        if value <= 24:
            return "Очень сложно"
        return "Опасно"
    lower, upper = int(bounds[0]), max(int(bounds[1]), int(bounds[0]) + 1)
    ratio = (value - lower) / max(1, upper - lower)
    if ratio <= 0.20:
        return "Легко"
    if ratio <= 0.45:
        return "Посильно"
    if ratio <= 0.70:
        return "Сложно"
    if ratio <= 1.00:
        return "Очень сложно"
    return "Опасно"


def with_public_difficulty_labels(
    missions: list[dict[str, Any]],
    bounds: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            **mission,
            "difficulty_label": mission_difficulty_label(
                int(mission.get("difficulty", 1)),
                bounds,
                mission.get("mission_type") or mission.get("type"),
            ),
        }
        for mission in missions
    ]


def calculate_hero_score(
    character: dict[str, Any],
    stat_name: str,
    used_assets: list[dict[str, Any]] | None = None,
) -> int:
    stat_key = stat_name.strip().lower()
    if stat_key not in STAT_NAMES:
        raise ValueError(f"Неизвестная характеристика: {stat_name}.")

    stats = _character_stats(character)
    score = hero_core_score(character, stat_key)
    race = str(character.get("race") or "").strip().casefold()
    ignored_types: set[str] = set()
    if race == "призрак":
        ignored_types.add("inventory")
    if race == "скелет":
        ignored_types.add("spells")

    counted_types: set[str] = set()
    asset_levels: list[int] = []
    for raw_asset in used_assets or []:
        asset_type = _normalize_asset_type(raw_asset.get("type") or raw_asset.get("field"))
        if (
            not asset_type
            or asset_type in ignored_types
            or asset_type in counted_types
            or not asset_is_active(raw_asset)
        ):
            continue
        asset_levels.append(int(raw_asset.get("level", 0)))
        counted_types.add(asset_type)
    return score + _diminished_asset_score(asset_levels)


def hero_core_score(character: dict[str, Any], stat_name: str) -> int:
    stat_key = stat_name.strip().lower()
    if stat_key not in STAT_NAMES:
        raise ValueError(f"Неизвестная характеристика: {stat_name}.")
    stats = _character_stats(character)
    return int(character.get("level", 1)) + int(stats.get(stat_key, 0))


def logic_tier_from_signals(signals: dict[str, Any]) -> int:
    if signals.get("goal") is not True:
        return 0
    if signals.get("method") is not True:
        return 1
    return 3 if signals.get("scene") is True else 2


def personal_contribution(base_score: int, logic_tier: int, core_score: int | None = None) -> int:
    if int(logic_tier) not in LOGIC_MULTIPLIERS:
        raise ValueError("logic_tier должен быть от 0 до 3.")
    tier = int(logic_tier)
    core = int(base_score if core_score is None else core_score)
    if tier == 0:
        return 0
    if tier == 1:
        return _round_half_up(core * 0.50)
    if tier == 2:
        return int(base_score)
    return int(base_score) + _round_half_up(core * 0.50)


def group_mission_status(
    mission_difficulty: int,
    contributions: list[dict[str, int]],
    teamwork_bonus: int = 0,
) -> str:
    mission_total = sum(int(entry["personal_contribution"]) for entry in contributions) + int(teamwork_bonus)
    if mission_total < int(mission_difficulty):
        return "failed"
    tiers = [int(entry["logic_tier"]) for entry in contributions]
    critical_threshold = math.ceil(int(mission_difficulty) * MISSION_CRITICAL_SUCCESS_MULTIPLIER)
    if mission_total >= critical_threshold and tiers and min(tiers) >= 2 and max(tiers) >= 3:
        return "critical_success"
    return "success"


def mission_teamwork_bonus(contributions: list[dict[str, int]]) -> int:
    if len(contributions) < 2:
        return 0
    tiers = [int(entry["logic_tier"]) for entry in contributions]
    if tiers and min(tiers) >= 3:
        return MISSION_TEAMWORK_BONUS
    return 0


def asset_is_active(asset: dict[str, Any], turn_id: int | None = None) -> bool:
    if asset.get("active") is False or int(asset.get("cooldown_remaining", 0) or 0) > 0:
        return False
    cooldown_until = int(asset.get("cooldown_until_turn", 0) or 0)
    return turn_id is None or cooldown_until < int(turn_id)


def asset_cooldown_remaining(asset: dict[str, Any], turn_id: int | None) -> int:
    if turn_id is None:
        return max(0, int(asset.get("cooldown_remaining", 0) or 0))
    cooldown_until = int(asset.get("cooldown_until_turn", 0) or 0)
    return max(0, cooldown_until - int(turn_id) + 1)


def asset_with_availability(asset: dict[str, Any], turn_id: int | None) -> dict[str, Any]:
    result = dict(asset)
    remaining = asset_cooldown_remaining(result, turn_id)
    result["active"] = remaining == 0
    if remaining:
        result["cooldown_remaining"] = remaining
    else:
        result.pop("cooldown_remaining", None)
    return result


def _cooldown_reference_turn_id(conn: sqlite3.Connection) -> int | None:
    open_row = conn.execute("SELECT id FROM turns WHERE status = 'open' ORDER BY id DESC LIMIT 1").fetchone()
    if open_row is not None:
        return int(open_row["id"])
    latest_row = conn.execute("SELECT id FROM turns ORDER BY id DESC LIMIT 1").fetchone()
    return None if latest_row is None else int(latest_row["id"]) + 1


def character_assets_with_availability(conn: sqlite3.Connection, character: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    turn_id = _cooldown_reference_turn_id(conn)
    return {
        "inventory": _annotate_assets(_character_inventory(character), turn_id),
        "spells": _annotate_assets(_character_spells(character), turn_id),
        "pets": _annotate_assets(_character_entities(character, "pet"), turn_id),
        "companions": _annotate_assets(_character_entities(character, "companion"), turn_id),
        "mounts": _annotate_assets(_character_entities(character, "mount"), turn_id),
    }


def should_trigger_death_outcome(
    mission_difficulty: int,
    personal_score: int,
    check_success: bool,
    mission_failed: bool = True,
) -> bool:
    margin = deadly_trial_personal_danger_threshold(mission_difficulty) - int(personal_score)
    return mission_failed and check_success is False and margin >= DEADLY_TRIAL_DEATH_THRESHOLD


def choose_death_outcome(rng: random.Random | random.SystemRandom | None = None) -> str:
    roller = rng or random.SystemRandom()
    return roller.choice(DEATH_OUTCOMES)


def ghost_character_state(character: dict[str, Any]) -> dict[str, Any]:
    stats = _character_stats(character)
    pool = (int(stats["сила"]) - 1) + (int(stats["ловкость"]) - 1)
    new_stats = dict(stats)
    new_stats["сила"] = 1
    new_stats["ловкость"] = 1
    new_stats["интеллект"] = int(stats["интеллект"]) + math.ceil(pool / 2)
    new_stats["харизма"] = int(stats["харизма"]) + math.floor(pool / 2)
    _assert_stat_total_preserved(stats, new_stats)
    return {**character, "race": "призрак", "stats": new_stats}


def skeleton_character_state(character: dict[str, Any]) -> dict[str, Any]:
    stats = _character_stats(character)
    pool = (int(stats["интеллект"]) - 1) + (int(stats["харизма"]) - 1)
    new_stats = dict(stats)
    new_stats["интеллект"] = 1
    new_stats["харизма"] = 1
    new_stats["сила"] = int(stats["сила"]) + math.ceil(pool / 2)
    new_stats["ловкость"] = int(stats["ловкость"]) + math.floor(pool / 2)
    _assert_stat_total_preserved(stats, new_stats)
    return {**character, "race": "скелет", "stats": new_stats}


def reincarnation_stat_pool(character: dict[str, Any]) -> int:
    return sum(int(value) for value in _character_stats(character).values())


def select_reincarnation_legacy_asset(
    character: dict[str, Any],
    rng: random.Random | random.SystemRandom | None = None,
) -> dict[str, Any] | None:
    assets = _all_character_assets(character)
    if not assets:
        return None
    max_level = max(int(asset["level"]) for asset in assets)
    candidates = [asset for asset in assets if int(asset["level"]) == max_level]
    roller = rng or random.SystemRandom()
    selected = dict(roller.choice(candidates))
    return {
        "legacy_type": selected["type"],
        "legacy_level": int(selected["level"]),
        "source_name": selected["name"],
        "legacy_name": None,
    }


def reincarnation_payload(
    character: dict[str, Any],
    rng: random.Random | random.SystemRandom | None = None,
) -> dict[str, Any]:
    return {
        "old_character_id": character.get("id") or character.get("character_id"),
        "locked_name": character.get("name"),
        "new_level": int(character.get("level", 1)),
        "stat_pool": reincarnation_stat_pool(character),
        "legacy": select_reincarnation_legacy_asset(character, rng),
        "lost_assets": {
            "inventory": _character_inventory(character),
            "spells": _character_spells(character),
            "pets": _character_entities(character, "pet"),
            "companions": _character_entities(character, "companion"),
            "mounts": _character_entities(character, "mount"),
        },
    }


def ensure_default_shop_items(conn: sqlite3.Connection) -> None:
    _reprice_active_system_shop_items(conn)
    system_active_count = conn.execute(
        "SELECT COUNT(*) AS count FROM shop_items WHERE status = 'active' AND source != 'player_sale'"
    ).fetchone()["count"]
    if system_active_count >= SHOP_SYSTEM_STOCK_SIZE:
        return
    _add_system_shop_items(conn, SHOP_SYSTEM_STOCK_SIZE - int(system_active_count))


def _reprice_active_system_shop_items(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT id, level, price
        FROM shop_items
        WHERE status = 'active' AND source != 'player_sale'
        """
    ).fetchall()
    updated = 0
    for row in rows:
        expected_price = shop_buy_price(int(row["level"]))
        if int(row["price"]) == expected_price:
            continue
        conn.execute(
            "UPDATE shop_items SET price = ? WHERE id = ?",
            (expected_price, int(row["id"])),
        )
        updated += 1
    if updated:
        conn.commit()
    return updated


def refresh_shop_for_new_turn(conn: sqlite3.Connection) -> int:
    ensure_default_shop_items(conn)
    active_system_rows = conn.execute(
        """
        SELECT id
        FROM shop_items
        WHERE status = 'active' AND source != 'player_sale'
        ORDER BY id
        """
    ).fetchall()
    active_count = len(active_system_rows)
    if active_count == 0:
        _add_system_shop_items(conn, SHOP_SYSTEM_STOCK_SIZE)
        return SHOP_SYSTEM_STOCK_SIZE

    selected_ids = [int(row["id"]) for row in active_system_rows]
    conn.executemany(
        "UPDATE shop_items SET status = 'sold', sold_at = CURRENT_TIMESTAMP WHERE id = ?",
        [(item_id,) for item_id in selected_ids],
    )
    _add_system_shop_items(conn, SHOP_SYSTEM_STOCK_SIZE)
    return len(selected_ids)


def refresh_shop_now(conn: sqlite3.Connection) -> dict[str, int]:
    repriced = _reprice_active_system_shop_items(conn)
    refreshed = refresh_shop_for_new_turn(conn)
    ensure_default_shop_items(conn)
    active_count = conn.execute(
        "SELECT COUNT(*) AS count FROM shop_items WHERE status = 'active' AND source != 'player_sale'"
    ).fetchone()["count"]
    return {
        "repriced": int(repriced),
        "refreshed": int(refreshed),
        "active_system_items": int(active_count),
    }


def list_shop_items(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure_default_shop_items(conn)
    turn_id = _cooldown_reference_turn_id(conn)
    rows = conn.execute(
        """
        SELECT *
        FROM shop_items
        WHERE status = 'active'
        ORDER BY level, price, id
        """
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = row_to_dict(row) or {}
        stored_asset = from_json(item.get("asset_json"), {})
        merged_asset = {
            **(stored_asset if isinstance(stored_asset, dict) else {}),
            "name": item["name"],
            "level": int(item["level"]),
        }
        items.append({**item, **asset_with_availability(merged_asset, turn_id)})
    return items


def player_can_buy_back(conn: sqlite3.Connection, telegram_id: int, shop_item_id: int) -> bool:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        return False
    row = conn.execute(
        """
        SELECT 1
        FROM shop_items
        WHERE id = ?
          AND status = 'active'
          AND source = 'player_sale'
          AND seller_character_id = ?
        LIMIT 1
        """,
        (shop_item_id, character["id"]),
    ).fetchone()
    return row is not None


def _add_system_shop_items(conn: sqlite3.Connection, count: int) -> None:
    for _ in range(max(0, count)):
        level = _roll_shop_item_level(conn)
        name = _generate_unique_shop_item_name(conn)
        conn.execute(
            """
            INSERT INTO shop_items (asset_type, name, level, asset_json, price, status, source)
            VALUES ('item', ?, ?, ?, ?, 'active', 'system')
            """,
            (name, level, to_json({"name": name, "level": level}), shop_buy_price(level)),
        )
    conn.commit()


def _roll_shop_item_level(conn: sqlite3.Connection) -> int:
    bounds = character_level_bounds(conn)
    rng = random.SystemRandom()
    if bounds is None:
        return rng.choice((1, 1, 2))
    min_level, max_level = bounds
    if min_level == max_level:
        low = max(1, min_level - 1)
        high = max_level + 1
    else:
        low = max(1, min_level)
        high = max_level + 1
    weighted_levels: list[int] = []
    for level in range(low, high + 1):
        weight = 3 if min_level <= level <= max_level else 1
        weighted_levels.extend([level] * weight)
    return rng.choice(weighted_levels or [1])


def _generate_unique_shop_item_name(conn: sqlite3.Connection) -> str:
    rng = random.SystemRandom()
    used_names = _all_asset_names(conn)
    candidates = [
        f"{prefix} {base} {suffix}"
        for prefix in SHOP_PREFIXES
        for base in SHOP_BASE_ITEMS
        for suffix in SHOP_SUFFIXES
    ]
    rng.shuffle(candidates)
    for candidate in candidates:
        name = " ".join(candidate.split())
        if name.casefold() not in used_names:
            return name
    raise ValueError("Не удалось сгенерировать уникальное имя товара для лавки.")


def _all_asset_names(conn: sqlite3.Connection) -> set[str]:
    names: set[str] = set()
    rows = conn.execute("SELECT * FROM characters WHERE is_active = 1").fetchall()
    for row in rows:
        character = row_to_dict(row) or {}
        for column in ("inventory_json", "spells_json"):
            for item in from_json(character.get(column), []):
                if isinstance(item, dict):
                    name = str(item.get("name", "")).strip()
                    if name:
                        names.add(name.casefold())
        for legacy_column, list_column in (
            ("pet_json", "pets_json"),
            ("companion_json", "companions_json"),
            ("mount_json", "mounts_json"),
        ):
            for entity in _entity_list(character, legacy_column, list_column):
                name = str(entity.get("name", "")).strip()
                if name:
                    names.add(name.casefold())
    shop_rows = conn.execute("SELECT name FROM shop_items").fetchall()
    for row in shop_rows:
        name = str(row["name"]).strip()
        if name:
            names.add(name.casefold())
    return names


def buy_shop_item(conn: sqlite3.Connection, telegram_id: int, shop_item_id: int) -> dict[str, Any]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа.")
    item = row_to_dict(
        conn.execute("SELECT * FROM shop_items WHERE id = ? AND status = 'active'", (shop_item_id,)).fetchone()
    )
    if not item:
        raise ValueError("Такого активного товара нет. Проверь /shop.")
    if int(character["gold"]) < int(item["price"]):
        raise ValueError(f"Не хватает дублонов: нужно {item['price']}, у тебя {character['gold']}.")

    asset_type = str(item.get("asset_type") or "item")
    stored_asset = from_json(item.get("asset_json"), {})
    reward = {
        **(stored_asset if isinstance(stored_asset, dict) else {}),
        "name": item["name"],
        "level": int(item["level"]),
    }
    if asset_type == "item":
        reward["uid"] = _new_item_uid()
    _ensure_unique_asset_name(character, reward["name"])
    new_gold = int(character["gold"]) - int(item["price"])
    _apply_bought_asset(conn, character, asset_type, reward, new_gold)
    conn.execute(
        "UPDATE shop_items SET status = 'sold', sold_at = CURRENT_TIMESTAMP WHERE id = ?",
        (shop_item_id,),
    )
    conn.commit()
    return {"asset_type": asset_type, "item": reward, "price": int(item["price"]), "gold": new_gold}


def sell_inventory_item(conn: sqlite3.Connection, telegram_id: int, item_uid: str) -> dict[str, Any]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа.")
    item_uid = item_uid.strip()
    inventory = from_json(character["inventory_json"], [])
    sold_item = next((item for item in inventory if isinstance(item, dict) and str(item.get("uid")) == item_uid), None)
    if not sold_item:
        raise ValueError("У тебя нет предмета с таким ID. Проверь /inventory или /sheet.")

    name = str(sold_item.get("name", "")).strip()
    level = int(sold_item.get("level", 1))
    if _active_shop_item_name_exists(conn, name):
        raise ValueError("В лавке уже есть предмет с таким именем. Для альфы одинаковые имена не продаем.")

    new_inventory = [item for item in inventory if not (isinstance(item, dict) and str(item.get("uid")) == item_uid)]
    sell_price = shop_sell_price(level)
    new_gold = int(character["gold"]) + sell_price
    conn.execute(
        "UPDATE characters SET inventory_json = ?, gold = ? WHERE id = ?",
        (to_json(new_inventory), new_gold, character["id"]),
    )
    cur = conn.execute(
        """
        INSERT INTO shop_items (asset_type, name, level, asset_json, price, status, source, seller_character_id)
        VALUES ('item', ?, ?, ?, ?, 'active', 'player_sale', ?)
        """,
        (name, level, to_json(sold_item), shop_buy_price(level), character["id"]),
    )
    conn.commit()
    return {
        "item": sold_item,
        "price": sell_price,
        "gold": new_gold,
        "listing_id": int(cur.lastrowid),
        "buyback_price": sell_price,
        "asset_type": "item",
    }


def sell_pet(conn: sqlite3.Connection, telegram_id: int, pet_name: str) -> dict[str, Any]:
    return _sell_named_entity(conn, telegram_id, pet_name, "pet")


def sell_mount(conn: sqlite3.Connection, telegram_id: int, mount_name: str) -> dict[str, Any]:
    return _sell_named_entity(conn, telegram_id, mount_name, "mount")


def offer_trade_pet(conn: sqlite3.Connection, telegram_id: int, pet_name: str) -> dict[str, Any]:
    return _offer_trade_named_entity(conn, telegram_id, pet_name, "pet")


def remove_trade_pet(conn: sqlite3.Connection, telegram_id: int, pet_name: str) -> dict[str, Any]:
    return _remove_trade_named_entity(conn, telegram_id, pet_name, "pet")


def offer_trade_companion(conn: sqlite3.Connection, telegram_id: int, companion_name: str) -> dict[str, Any]:
    return _offer_trade_named_entity(conn, telegram_id, companion_name, "companion")


def remove_trade_companion(conn: sqlite3.Connection, telegram_id: int, companion_name: str) -> dict[str, Any]:
    return _remove_trade_named_entity(conn, telegram_id, companion_name, "companion")


def offer_trade_mount(conn: sqlite3.Connection, telegram_id: int, mount_name: str) -> dict[str, Any]:
    return _offer_trade_named_entity(conn, telegram_id, mount_name, "mount")


def remove_trade_mount(conn: sqlite3.Connection, telegram_id: int, mount_name: str) -> dict[str, Any]:
    return _remove_trade_named_entity(conn, telegram_id, mount_name, "mount")


def _apply_bought_asset(
    conn: sqlite3.Connection,
    character: dict[str, Any],
    asset_type: str,
    reward: dict[str, Any],
    new_gold: int,
) -> None:
    if asset_type == "item":
        inventory = from_json(character["inventory_json"], [])
        conn.execute(
            "UPDATE characters SET inventory_json = ?, gold = ? WHERE id = ?",
            (to_json([*inventory, reward]), new_gold, character["id"]),
        )
        return
    if asset_type == "pet":
        pets = _entity_list(character, "pet_json", "pets_json")
        conn.execute(
            "UPDATE characters SET pets_json = ?, gold = ? WHERE id = ?",
            (to_json([*pets, reward]), new_gold, character["id"]),
        )
        return
    if asset_type == "mount":
        mounts = _entity_list(character, "mount_json", "mounts_json")
        conn.execute(
            "UPDATE characters SET mounts_json = ?, gold = ? WHERE id = ?",
            (to_json([*mounts, reward]), new_gold, character["id"]),
        )
        return
    raise ValueError("Лавка пока не умеет выдавать этот тип актива.")


def _sell_named_entity(conn: sqlite3.Connection, telegram_id: int, entity_name: str, entity_type: str) -> dict[str, Any]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа.")
    entity_name = entity_name.strip()
    entities = _character_entity_collection(character, entity_type)
    sold_entity = next((entity for entity in entities if _entity_name(entity) == entity_name.casefold()), None)
    if not sold_entity:
        raise ValueError(f"У тебя нет {'питомца' if entity_type == 'pet' else 'маунта'} с таким именем. Проверь /allies или /sheet.")
    name = str(sold_entity.get("name", "")).strip()
    level = int(sold_entity.get("level", 1))
    if _active_shop_item_name_exists(conn, name):
        raise ValueError("В лавке уже есть актив с таким именем. Для альфы одинаковые имена не продаем.")

    remaining = [entity for entity in entities if _entity_name(entity) != name.casefold()]
    sell_price = shop_sell_price(level)
    new_gold = int(character["gold"]) + sell_price
    column = "pets_json" if entity_type == "pet" else "mounts_json"
    conn.execute(
        f"UPDATE characters SET {column} = ?, gold = ? WHERE id = ?",
        (to_json(remaining), new_gold, character["id"]),
    )
    cur = conn.execute(
        """
        INSERT INTO shop_items (asset_type, name, level, asset_json, price, status, source, seller_character_id)
        VALUES (?, ?, ?, ?, ?, 'active', 'player_sale', ?)
        """,
        (entity_type, name, level, to_json(sold_entity), shop_buy_price(level), character["id"]),
    )
    conn.commit()
    return {
        "item": sold_entity,
        "price": sell_price,
        "gold": new_gold,
        "listing_id": int(cur.lastrowid),
        "buyback_price": sell_price,
        "asset_type": entity_type,
    }


def buy_back_shop_item(conn: sqlite3.Connection, telegram_id: int, shop_item_id: int) -> dict[str, Any]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа.")

    item = row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM shop_items
            WHERE id = ?
              AND status = 'active'
              AND source = 'player_sale'
              AND seller_character_id = ?
            """,
            (shop_item_id, character["id"]),
        ).fetchone()
    )
    if not item:
        raise ValueError("Этот товар нельзя выкупить обратно. Возможно, он уже куплен или не принадлежит тебе.")

    buyback_price = shop_sell_price(int(item["level"]))
    if int(character["gold"]) < buyback_price:
        raise ValueError(f"Не хватает дублонов для выкупа: нужно {buyback_price}, у тебя {character['gold']}.")

    asset_type = str(item.get("asset_type") or "item")
    stored_asset = from_json(item.get("asset_json"), {})
    reward = {
        **(stored_asset if isinstance(stored_asset, dict) else {}),
        "name": item["name"],
        "level": int(item["level"]),
    }
    if asset_type == "item":
        reward["uid"] = _new_item_uid()
    _ensure_unique_asset_name(character, reward["name"])

    new_gold = int(character["gold"]) - buyback_price
    _apply_bought_asset(conn, character, asset_type, reward, new_gold)
    conn.execute(
        "UPDATE shop_items SET status = 'sold', sold_at = CURRENT_TIMESTAMP WHERE id = ?",
        (shop_item_id,),
    )
    conn.commit()
    return {"asset_type": asset_type, "item": reward, "price": buyback_price, "gold": new_gold}


def shop_buy_price(level: int) -> int:
    return max(1, int(level) * SHOP_BUY_PRICE_PER_LEVEL)


def shop_sell_price(level: int) -> int:
    return max(1, int(level) * SHOP_SELL_PRICE_PER_LEVEL)


def tavern_rest_offer(conn: sqlite3.Connection, telegram_id: int) -> dict[str, Any]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа.")
    turn_id = _cooldown_reference_turn_id(conn)
    cooling_assets = [
        asset_with_availability(asset, turn_id)
        for asset in _all_character_assets(character, include_metadata=True)
        if asset_cooldown_remaining(asset, turn_id) > 0
    ]
    levels_total = sum(int(asset.get("level", 1)) for asset in cooling_assets)
    price = max(
        1,
        math.ceil(int(character["level"]) / TAVERN_LEVEL_PRICE_DIVISOR)
        + math.ceil(levels_total / TAVERN_COOLDOWN_PRICE_DIVISOR),
    )
    return {
        "available": bool(cooling_assets),
        "price": price,
        "assets": cooling_assets,
        "asset_count": len(cooling_assets),
        "asset_levels_total": levels_total,
        "gold": int(character["gold"]),
    }


def rest_in_tavern(conn: sqlite3.Connection, telegram_id: int) -> dict[str, Any]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа.")
    offer = tavern_rest_offer(conn, telegram_id)
    if not offer["available"]:
        raise ValueError("Все твои активы уже готовы. Отдых сейчас не нужен.")
    price = int(offer["price"])
    if int(character["gold"]) < price:
        raise ValueError(f"Не хватает дублонов на отдых: нужно {price}, у тебя {character['gold']}.")
    updates = {
        "inventory_json": _clear_collection_cooldowns(_character_inventory(character)),
        "spells_json": _clear_collection_cooldowns(_character_spells(character)),
        "pets_json": _clear_collection_cooldowns(_character_entities(character, "pet")),
        "companions_json": _clear_collection_cooldowns(_character_entities(character, "companion")),
        "mounts_json": _clear_collection_cooldowns(_character_entities(character, "mount")),
    }
    new_gold = int(character["gold"]) - price
    conn.execute(
        """
        UPDATE characters
        SET inventory_json = ?, spells_json = ?, pets_json = ?, companions_json = ?, mounts_json = ?, gold = ?
        WHERE id = ?
        """,
        (
            to_json(updates["inventory_json"]),
            to_json(updates["spells_json"]),
            to_json(updates["pets_json"]),
            to_json(updates["companions_json"]),
            to_json(updates["mounts_json"]),
            new_gold,
            character["id"],
        ),
    )
    conn.commit()
    return {**offer, "gold": new_gold}


def list_craft_assets(conn: sqlite3.Connection, telegram_id: int) -> list[dict[str, Any]]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа.")
    return _annotate_assets(_craft_assets_for_character(character), _cooldown_reference_turn_id(conn))


def get_current_turn_craft_request(conn: sqlite3.Connection, telegram_id: int) -> dict[str, Any] | None:
    turn = get_open_turn(conn)
    if not turn:
        return None
    character = get_character_for_player(conn, telegram_id)
    if not character:
        return None
    row = conn.execute(
        """
        SELECT *
        FROM craft_requests
        WHERE turn_id = ? AND character_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (turn["id"], character["id"]),
    ).fetchone()
    request = row_to_dict(row)
    if not request:
        return None
    return {
        **request,
        "base": from_json(request.get("base_json"), {}),
        "material": from_json(request.get("material_json"), {}),
        "result": from_json(request.get("result_json"), {}),
    }


def create_craft_request(
    conn: sqlite3.Connection,
    telegram_id: int,
    base_token: str,
    material_token: str,
) -> dict[str, Any]:
    turn = get_open_turn(conn)
    if not turn:
        raise ValueError("Сейчас нет открытого хода. Крафт можно начать только во время хода.")
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа.")
    existing = conn.execute(
        """
        SELECT 1
        FROM craft_requests
        WHERE turn_id = ? AND character_id = ?
        LIMIT 1
        """,
        (turn["id"], character["id"]),
    ).fetchone()
    if existing:
        raise ValueError("В этом ходу у тебя уже есть крафт. Можно сделать только один крафт за ход.")
    if base_token == material_token:
        raise ValueError("Основа и материал не могут быть одним и тем же активом.")

    assets = _craft_assets_for_character(character)
    by_token = {asset["token"]: asset for asset in assets}
    base = by_token.get(base_token)
    material = by_token.get(material_token)
    if not base or not material:
        raise ValueError("Один из активов уже не найден. Открой крафт заново.")

    _remove_craft_assets(conn, character, [base, material])
    try:
        cur = conn.execute(
            """
            INSERT INTO craft_requests (turn_id, character_id, base_json, material_json)
            VALUES (?, ?, ?, ?)
            """,
            (turn["id"], character["id"], to_json(_craft_snapshot(base)), to_json(_craft_snapshot(material))),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("В этом ходу у тебя уже есть крафт. Можно сделать только один крафт за ход.") from exc
    conn.commit()
    return {
        "id": int(cur.lastrowid),
        "turn_id": int(turn["id"]),
        "character_id": int(character["id"]),
        "character_name": character["name"],
        "base": _craft_snapshot(base),
        "material": _craft_snapshot(material),
    }


def craft_result_level(base_level: int, material_level: int, relationship: str) -> int:
    normalized = str(relationship or "weak").strip().lower()
    multiplier = CRAFT_RELATIONSHIP_MULTIPLIERS.get(normalized, CRAFT_RELATIONSHIP_MULTIPLIERS["weak"])
    bonus = max(1, math.ceil(min(int(base_level), int(material_level)) * multiplier))
    return max(int(base_level), int(material_level)) + bonus


def pending_craft_publications(conn: sqlite3.Connection, turn_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            craft_requests.*,
            characters.name AS character_name,
            players.telegram_id
        FROM craft_requests
        JOIN characters ON characters.id = craft_requests.character_id
        JOIN players ON players.id = characters.player_id
        WHERE craft_requests.turn_id = ?
          AND craft_requests.status = 'completed'
          AND craft_requests.published_at IS NULL
          AND players.notify_enabled = 1
        ORDER BY craft_requests.id
        """,
        (turn_id,),
    ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def mark_craft_published(conn: sqlite3.Connection, craft_request_id: int) -> None:
    conn.execute("UPDATE craft_requests SET published_at = CURRENT_TIMESTAMP WHERE id = ?", (craft_request_id,))
    conn.commit()


def _active_shop_item_name_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM shop_items WHERE status = 'active' AND lower(name) = lower(?) LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def find_character_for_trade(conn: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    target = query.strip().lstrip("@")
    if not target:
        return None
    row = conn.execute(
        """
        SELECT characters.*, players.telegram_id, players.username, players.notify_enabled
        FROM characters
        JOIN players ON players.id = characters.player_id
        WHERE players.notify_enabled = 1
          AND characters.is_active = 1
          AND (
              lower(players.username) = lower(?)
              OR lower(characters.name) = lower(?)
          )
        ORDER BY characters.id
        LIMIT 1
        """,
        (target, target),
    ).fetchone()
    return row_to_dict(row)


def start_trade(conn: sqlite3.Connection, initiator_telegram_id: int, target_query: str) -> dict[str, Any]:
    initiator = get_character_for_player(conn, initiator_telegram_id)
    if not initiator:
        raise ValueError("Сначала создай персонажа.")
    target = find_character_for_trade(conn, target_query)
    if not target:
        raise ValueError("Не нашел персонажа или Telegram username для обмена.")
    if int(target["id"]) == int(initiator["id"]):
        raise ValueError("Нельзя начать обмен с самим собой.")
    if _active_trade_for_character(conn, int(initiator["id"])) or _active_trade_for_character(conn, int(target["id"])):
        raise ValueError("У одного из участников уже есть активный обмен.")

    cur = conn.execute(
        """
        INSERT INTO trades (
            initiator_character_id,
            target_character_id,
            status
        )
        VALUES (?, ?, 'pending')
        """,
        (initiator["id"], target["id"]),
    )
    conn.commit()
    return get_trade(conn, int(cur.lastrowid)) or {}


def get_trade(conn: sqlite3.Connection, trade_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    return row_to_dict(row)


def get_active_trade_for_player(conn: sqlite3.Connection, telegram_id: int) -> dict[str, Any] | None:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        return None
    return _active_trade_for_character(conn, int(character["id"]))


def offer_trade_item(conn: sqlite3.Connection, telegram_id: int, item_uid: str) -> dict[str, Any]:
    character, trade, side = _trade_context_for_player(conn, telegram_id)
    item_uid = item_uid.strip()
    inventory = from_json(character["inventory_json"], [])
    if not any(str(item.get("uid")) == item_uid for item in inventory if isinstance(item, dict)):
        raise ValueError("У тебя нет предмета с таким ID. Проверь /inventory.")

    column = f"{side}_items_json"
    offered_items = from_json(trade[column], [])
    if item_uid not in offered_items:
        offered_items.append(item_uid)
    _update_trade_offer(conn, int(trade["id"]), column, to_json(offered_items))
    return get_trade(conn, int(trade["id"])) or {}


def _offer_trade_named_entity(conn: sqlite3.Connection, telegram_id: int, entity_name: str, entity_type: str) -> dict[str, Any]:
    character, trade, side = _trade_context_for_player(conn, telegram_id)
    entity_name = entity_name.strip()
    entities = _character_entity_collection(character, entity_type)
    if not any(_entity_name(entity) == entity_name.casefold() for entity in entities):
        entity_label = {
            "pet": "питомца",
            "companion": "спутника",
            "mount": "маунта",
        }.get(entity_type, "актива")
        raise ValueError(
            f"У тебя нет {entity_label} с таким именем. Проверь /allies или /sheet."
        )
    column = f"{side}_{entity_type}s_json"
    offered = from_json(trade[column], [])
    if entity_name not in offered:
        offered.append(entity_name)
    _update_trade_offer(conn, int(trade["id"]), column, to_json(offered))
    return get_trade(conn, int(trade["id"])) or {}


def remove_trade_item(conn: sqlite3.Connection, telegram_id: int, item_uid: str) -> dict[str, Any]:
    _character, trade, side = _trade_context_for_player(conn, telegram_id)
    column = f"{side}_items_json"
    offered_items = [uid for uid in from_json(trade[column], []) if uid != item_uid.strip()]
    _update_trade_offer(conn, int(trade["id"]), column, to_json(offered_items))
    return get_trade(conn, int(trade["id"])) or {}


def _remove_trade_named_entity(conn: sqlite3.Connection, telegram_id: int, entity_name: str, entity_type: str) -> dict[str, Any]:
    _character, trade, side = _trade_context_for_player(conn, telegram_id)
    column = f"{side}_{entity_type}s_json"
    offered = [name for name in from_json(trade[column], []) if name.casefold() != entity_name.strip().casefold()]
    _update_trade_offer(conn, int(trade["id"]), column, to_json(offered))
    return get_trade(conn, int(trade["id"])) or {}


def offer_trade_gold(conn: sqlite3.Connection, telegram_id: int, amount: int) -> dict[str, Any]:
    character, trade, side = _trade_context_for_player(conn, telegram_id)
    if amount < 0:
        raise ValueError("Количество дублонов не может быть отрицательным.")
    if amount > int(character["gold"]):
        raise ValueError(f"У тебя только {character['gold']} дублонов.")
    _update_trade_offer(conn, int(trade["id"]), f"{side}_gold", amount)
    return get_trade(conn, int(trade["id"])) or {}


def cancel_trade(conn: sqlite3.Connection, telegram_id: int) -> dict[str, Any]:
    _character, trade, _side = _trade_context_for_player(conn, telegram_id)
    conn.execute(
        "UPDATE trades SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (trade["id"],),
    )
    conn.commit()
    return get_trade(conn, int(trade["id"])) or trade


def accept_trade(conn: sqlite3.Connection, telegram_id: int) -> tuple[dict[str, Any], bool]:
    character, trade, side = _trade_context_for_player(conn, telegram_id)
    conn.execute(
        f"""
        UPDATE trades
        SET {side}_confirmed = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (trade["id"],),
    )
    trade = get_trade(conn, int(trade["id"])) or trade
    if int(trade["initiator_confirmed"]) and int(trade["target_confirmed"]):
        _complete_trade(conn, trade)
        return get_trade(conn, int(trade["id"])) or trade, True
    conn.commit()
    return trade, False


def _active_trade_for_character(conn: sqlite3.Connection, character_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT *
        FROM trades
        WHERE status = 'pending'
          AND (initiator_character_id = ? OR target_character_id = ?)
        ORDER BY id DESC
        LIMIT 1
        """,
        (character_id, character_id),
    ).fetchone()
    return row_to_dict(row)


def _trade_context_for_player(conn: sqlite3.Connection, telegram_id: int) -> tuple[dict[str, Any], dict[str, Any], str]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа.")
    trade = _active_trade_for_character(conn, int(character["id"]))
    if not trade:
        raise ValueError("У тебя нет активного обмена.")
    if int(trade["initiator_character_id"]) == int(character["id"]):
        return character, trade, "initiator"
    return character, trade, "target"


def _update_trade_offer(conn: sqlite3.Connection, trade_id: int, column: str, value: Any) -> None:
    allowed_columns = {
        "initiator_items_json",
        "target_items_json",
        "initiator_pets_json",
        "target_pets_json",
        "initiator_companions_json",
        "target_companions_json",
        "initiator_mounts_json",
        "target_mounts_json",
        "initiator_gold",
        "target_gold",
    }
    if column not in allowed_columns:
        raise ValueError("Нельзя изменить это поле обмена.")
    conn.execute(
        f"""
        UPDATE trades
        SET {column} = ?,
            initiator_confirmed = 0,
            target_confirmed = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (value, trade_id),
    )
    conn.commit()


def _complete_trade(conn: sqlite3.Connection, trade: dict[str, Any]) -> None:
    initiator = _character_by_id(conn, int(trade["initiator_character_id"]))
    target = _character_by_id(conn, int(trade["target_character_id"]))
    if not initiator or not target:
        raise ValueError("Один из участников обмена не найден.")

    initiator_items = from_json(trade["initiator_items_json"], [])
    target_items = from_json(trade["target_items_json"], [])
    initiator_pets = from_json(trade["initiator_pets_json"], [])
    target_pets = from_json(trade["target_pets_json"], [])
    initiator_companions = from_json(trade["initiator_companions_json"], [])
    target_companions = from_json(trade["target_companions_json"], [])
    initiator_mounts = from_json(trade["initiator_mounts_json"], [])
    target_mounts = from_json(trade["target_mounts_json"], [])
    initiator_gold = int(trade["initiator_gold"])
    target_gold = int(trade["target_gold"])

    if initiator_gold > int(initiator["gold"]) or target_gold > int(target["gold"]):
        raise ValueError("У одного из участников не хватает дублонов.")

    initiator_inventory = from_json(initiator["inventory_json"], [])
    target_inventory = from_json(target["inventory_json"], [])
    initiator_pet_list = _entity_list(initiator, "pet_json", "pets_json")
    target_pet_list = _entity_list(target, "pet_json", "pets_json")
    initiator_companion_list = _entity_list(initiator, "companion_json", "companions_json")
    target_companion_list = _entity_list(target, "companion_json", "companions_json")
    initiator_mount_list = _entity_list(initiator, "mount_json", "mounts_json")
    target_mount_list = _entity_list(target, "mount_json", "mounts_json")
    moved_from_initiator, initiator_remaining = _split_inventory_by_uids(initiator_inventory, initiator_items)
    moved_from_target, target_remaining = _split_inventory_by_uids(target_inventory, target_items)
    moved_pets_from_initiator, initiator_pets_remaining = _split_entities_by_names(initiator_pet_list, initiator_pets)
    moved_pets_from_target, target_pets_remaining = _split_entities_by_names(target_pet_list, target_pets)
    moved_companions_from_initiator, initiator_companions_remaining = _split_entities_by_names(initiator_companion_list, initiator_companions)
    moved_companions_from_target, target_companions_remaining = _split_entities_by_names(target_companion_list, target_companions)
    moved_mounts_from_initiator, initiator_mounts_remaining = _split_entities_by_names(initiator_mount_list, initiator_mounts)
    moved_mounts_from_target, target_mounts_remaining = _split_entities_by_names(target_mount_list, target_mounts)
    if len(moved_from_initiator) != len(set(initiator_items)) or len(moved_from_target) != len(set(target_items)):
        raise ValueError("Один из предметов обмена больше не принадлежит участнику.")
    if len(moved_pets_from_initiator) != len(set(name.casefold() for name in initiator_pets)) or len(moved_pets_from_target) != len(set(name.casefold() for name in target_pets)):
        raise ValueError("Один из питомцев больше не принадлежит участнику.")
    if len(moved_companions_from_initiator) != len(set(name.casefold() for name in initiator_companions)) or len(moved_companions_from_target) != len(set(name.casefold() for name in target_companions)):
        raise ValueError("Один из спутников больше не принадлежит участнику.")
    if len(moved_mounts_from_initiator) != len(set(name.casefold() for name in initiator_mounts)) or len(moved_mounts_from_target) != len(set(name.casefold() for name in target_mounts)):
        raise ValueError("Один из маунтов больше не принадлежит участнику.")

    initiator_final_inventory = [*initiator_remaining, *moved_from_target]
    target_final_inventory = [*target_remaining, *moved_from_initiator]
    initiator_final_pets = [*initiator_pets_remaining, *moved_pets_from_target]
    target_final_pets = [*target_pets_remaining, *moved_pets_from_initiator]
    initiator_final_companions = [*initiator_companions_remaining, *moved_companions_from_target]
    target_final_companions = [*target_companions_remaining, *moved_companions_from_initiator]
    initiator_final_mounts = [*initiator_mounts_remaining, *moved_mounts_from_target]
    target_final_mounts = [*target_mounts_remaining, *moved_mounts_from_initiator]
    _validate_character_assets_unique(
        initiator,
        initiator_final_inventory,
        pets=initiator_final_pets,
        companions=initiator_final_companions,
        mounts=initiator_final_mounts,
    )
    _validate_character_assets_unique(
        target,
        target_final_inventory,
        pets=target_final_pets,
        companions=target_final_companions,
        mounts=target_final_mounts,
    )

    conn.execute(
        "UPDATE characters SET inventory_json = ?, pets_json = ?, companions_json = ?, mounts_json = ?, gold = ? WHERE id = ?",
        (
            to_json(initiator_final_inventory),
            to_json(initiator_final_pets),
            to_json(initiator_final_companions),
            to_json(initiator_final_mounts),
            int(initiator["gold"]) - initiator_gold + target_gold,
            initiator["id"],
        ),
    )
    conn.execute(
        "UPDATE characters SET inventory_json = ?, pets_json = ?, companions_json = ?, mounts_json = ?, gold = ? WHERE id = ?",
        (
            to_json(target_final_inventory),
            to_json(target_final_pets),
            to_json(target_final_companions),
            to_json(target_final_mounts),
            int(target["gold"]) - target_gold + initiator_gold,
            target["id"],
        ),
    )
    conn.execute(
        "UPDATE trades SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (trade["id"],),
    )
    conn.commit()


def _character_by_id(conn: sqlite3.Connection, character_id: int) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone())


def _split_inventory_by_uids(inventory: list[dict[str, Any]], item_uids: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    wanted = set(item_uids)
    moved: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for item in inventory:
        if isinstance(item, dict) and str(item.get("uid")) in wanted:
            moved.append(item)
        else:
            remaining.append(item)
    return moved, remaining


def _split_entities_by_names(entities: list[dict[str, Any]], names: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    wanted = {name.casefold() for name in names}
    moved: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for entity in entities:
        if _entity_name(entity) in wanted:
            moved.append(entity)
        else:
            remaining.append(entity)
    return moved, remaining


def _validate_character_assets_unique(
    character: dict[str, Any],
    inventory: list[dict[str, Any]],
    pets: list[dict[str, Any]] | None = None,
    companions: list[dict[str, Any]] | None = None,
    mounts: list[dict[str, Any]] | None = None,
) -> None:
    names: list[str] = []
    names.extend(item.get("name", "") for item in inventory if isinstance(item, dict))
    names.extend(spell.get("name", "") for spell in from_json(character["spells_json"], []) if isinstance(spell, dict))
    names.extend(entity.get("name", "") for entity in (pets if pets is not None else _entity_list(character, "pet_json", "pets_json")))
    names.extend(entity.get("name", "") for entity in (companions if companions is not None else _entity_list(character, "companion_json", "companions_json")))
    names.extend(entity.get("name", "") for entity in (mounts if mounts is not None else _entity_list(character, "mount_json", "mounts_json")))
    _validate_unique_names(names)


def _character_entity_collection(character: dict[str, Any], entity_type: str) -> list[dict[str, Any]]:
    if entity_type == "pet":
        return _entity_list(character, "pet_json", "pets_json")
    if entity_type == "companion":
        return _entity_list(character, "companion_json", "companions_json")
    if entity_type == "mount":
        return _entity_list(character, "mount_json", "mounts_json")
    raise ValueError("Неизвестный тип сущности.")


def _entity_name(entity: dict[str, Any]) -> str:
    return str(entity.get("name", "")).strip().casefold()


def _best_level(assets: list[dict[str, Any]]) -> int:
    levels = [int(asset.get("level", 0)) for asset in assets if isinstance(asset, dict)]
    return max(levels, default=0)


def _character_stats(character: dict[str, Any]) -> dict[str, int]:
    raw_stats = character.get("stats")
    if isinstance(raw_stats, dict):
        return {name: int(raw_stats.get(name, DEFAULT_STATS[name])) for name in STAT_NAMES}
    return from_json(character.get("stats_json"), DEFAULT_STATS)


def _character_inventory(character: dict[str, Any]) -> list[dict[str, Any]]:
    raw_inventory = character.get("inventory")
    if isinstance(raw_inventory, list):
        return [item for item in raw_inventory if isinstance(item, dict)]
    return from_json(character.get("inventory_json"), [])


def _character_spells(character: dict[str, Any]) -> list[dict[str, Any]]:
    raw_spells = character.get("spells")
    if isinstance(raw_spells, list):
        return [spell for spell in raw_spells if isinstance(spell, dict)]
    return from_json(character.get("spells_json"), [])


def _character_entities(character: dict[str, Any], entity_type: str) -> list[dict[str, Any]]:
    if entity_type == "pet":
        raw = character.get("pets")
        if isinstance(raw, list):
            return [entity for entity in raw if isinstance(entity, dict)]
        return _entity_list(character, "pet_json", "pets_json")
    if entity_type == "companion":
        raw = character.get("companions")
        if isinstance(raw, list):
            return [entity for entity in raw if isinstance(entity, dict)]
        return _entity_list(character, "companion_json", "companions_json")
    if entity_type == "mount":
        raw = character.get("mounts")
        if isinstance(raw, list):
            return [entity for entity in raw if isinstance(entity, dict)]
        return _entity_list(character, "mount_json", "mounts_json")
    return []


def _all_character_assets(character: dict[str, Any], include_metadata: bool = False) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for asset_type, collection in (
        ("inventory", _character_inventory(character)),
        ("spells", _character_spells(character)),
        ("pet", _character_entities(character, "pet")),
        ("companion", _character_entities(character, "companion")),
        ("mount", _character_entities(character, "mount")),
    ):
        for asset in collection:
            name = str(asset.get("name") or "").strip()
            if not name:
                continue
            payload = dict(asset) if include_metadata else {}
            assets.append({**payload, "type": asset_type, "name": name, "level": int(asset.get("level", 1))})
    return assets


def _clear_collection_cooldowns(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleared: list[dict[str, Any]] = []
    for asset in assets:
        item = dict(asset)
        item.pop("cooldown_until_turn", None)
        item.pop("cooldown_remaining", None)
        item.pop("active", None)
        cleared.append(item)
    return cleared


def _annotate_assets(assets: list[dict[str, Any]], turn_id: int | None) -> list[dict[str, Any]]:
    return [asset_with_availability(asset, turn_id) for asset in assets]


def _craft_assets_for_character(character: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for item in _character_inventory(character):
        name = str(item.get("name") or "").strip()
        uid = str(item.get("uid") or "").strip()
        if name and uid:
            assets.append(
                {
                    "token": f"inventory:{uid}",
                    "type": "inventory",
                    "type_label": "предмет",
                    "name": name,
                    "level": int(item.get("level", 1)),
                    "cooldown_until_turn": int(item.get("cooldown_until_turn", 0) or 0),
                    "cooldown_turns": int(item.get("cooldown_turns", 0) or 0),
                    "uid": uid,
                    "source": "inventory_json",
                }
            )
    for index, spell in enumerate(_character_spells(character)):
        name = str(spell.get("name") or "").strip()
        if name:
            assets.append(_craft_indexed_asset("spells", "заклинание", "spells_json", index, spell))
    for entity_type, label, column in (
        ("pet", "питомец/фамильяр", "pets_json"),
        ("companion", "спутник/спутница", "companions_json"),
        ("mount", "маунт", "mounts_json"),
    ):
        for index, entity in enumerate(_character_entities(character, entity_type)):
            name = str(entity.get("name") or "").strip()
            if name:
                assets.append(_craft_indexed_asset(entity_type, label, column, index, entity))
    return assets


def _craft_indexed_asset(
    asset_type: str,
    type_label: str,
    source: str,
    index: int,
    asset: dict[str, Any],
) -> dict[str, Any]:
    return {
        "token": f"{asset_type}:{index}",
        "type": asset_type,
        "type_label": type_label,
        "name": str(asset.get("name") or "").strip(),
        "level": int(asset.get("level", 1)),
        "cooldown_until_turn": int(asset.get("cooldown_until_turn", 0) or 0),
        "cooldown_turns": int(asset.get("cooldown_turns", 0) or 0),
        "index": index,
        "source": source,
    }


def _craft_snapshot(asset: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        "type": asset["type"],
        "type_label": asset.get("type_label") or _craft_type_label(asset["type"]),
        "name": asset["name"],
        "level": int(asset.get("level", 1)),
        "token": asset.get("token"),
        "source": asset.get("source"),
    }
    if asset.get("uid"):
        snapshot["uid"] = asset["uid"]
    if "index" in asset:
        snapshot["index"] = int(asset["index"])
    if int(asset.get("cooldown_until_turn", 0) or 0) > 0:
        snapshot["cooldown_until_turn"] = int(asset["cooldown_until_turn"])
    if int(asset.get("cooldown_turns", 0) or 0) > 0:
        snapshot["cooldown_turns"] = int(asset["cooldown_turns"])
    return snapshot


def _remove_craft_assets(
    conn: sqlite3.Connection,
    character: dict[str, Any],
    assets: list[dict[str, Any]],
) -> None:
    inventory = _character_inventory(character)
    spells = _character_spells(character)
    pets = _character_entities(character, "pet")
    companions = _character_entities(character, "companion")
    mounts = _character_entities(character, "mount")

    indexed_removals: dict[str, list[dict[str, Any]]] = {"spells": [], "pet": [], "companion": [], "mount": []}
    for asset in assets:
        asset_type = asset["type"]
        if asset_type == "inventory":
            uid = str(asset.get("uid") or "").strip()
            inventory = [item for item in inventory if str(item.get("uid") or "") != uid]
            continue
        if asset_type not in indexed_removals:
            raise ValueError("Неизвестный тип актива для крафта.")
        indexed_removals[asset_type].append(asset)

    collections = {
        "spells": spells,
        "pet": pets,
        "companion": companions,
        "mount": mounts,
    }
    for asset_type, removals in indexed_removals.items():
        collection = collections[asset_type]
        for asset in sorted(removals, key=lambda item: int(item.get("index", -1)), reverse=True):
            index = int(asset.get("index", -1))
            name = str(asset.get("name") or "").strip()
            if index < 0 or index >= len(collection) or str(collection[index].get("name") or "").strip() != name:
                raise ValueError("Один из активов уже изменился. Открой крафт заново.")
            del collection[index]

    conn.execute(
        """
        UPDATE characters
        SET inventory_json = ?,
            spells_json = ?,
            pets_json = ?,
            companions_json = ?,
            mounts_json = ?
        WHERE id = ?
        """,
        (to_json(inventory), to_json(spells), to_json(pets), to_json(companions), to_json(mounts), character["id"]),
    )


def _craft_type_label(asset_type: str) -> str:
    if asset_type == "inventory":
        return "предмет"
    if asset_type == "spells":
        return "заклинание"
    if asset_type == "pet":
        return "питомец/фамильяр"
    if asset_type == "companion":
        return "спутник/спутница"
    if asset_type == "mount":
        return "маунт"
    return "актив"


def _normalize_asset_type(value: Any) -> str:
    asset_type = str(value or "").strip().lower()
    if asset_type in {"item", "inventory"}:
        return "inventory"
    if asset_type in {"spell", "spells"}:
        return "spells"
    if asset_type in {"pet", "familiar"}:
        return "pet"
    if asset_type in {"companion", "mount"}:
        return asset_type
    return ""


def _assert_stat_total_preserved(old_stats: dict[str, int], new_stats: dict[str, int]) -> None:
    old_total = sum(int(old_stats.get(name, 0)) for name in STAT_NAMES)
    new_total = sum(int(new_stats.get(name, 0)) for name in STAT_NAMES)
    if old_total != new_total:
        raise ValueError("Посмертное перераспределение характеристик должно сохранять сумму характеристик.")


def roll_reward(
    mission_difficulty: int,
    mission_type: str | None = None,
    *,
    reward_difficulty: int | None = None,
) -> dict[str, Any]:
    rng = random.SystemRandom()
    is_rare = rng.random() < RARE_REWARD_CHANCE
    allowed_types = list(RARE_REWARD_TYPES if is_rare else COMMON_REWARD_TYPES)
    personal_scale = int(reward_difficulty or mission_difficulty)
    base_level = _roll_reward_level(rng, personal_scale)
    is_deadly = _normalize_mission_type(mission_type) == MISSION_TYPE_DEADLY_TRIAL
    level = deadly_trial_reward_level(base_level, mission_difficulty) if is_deadly else base_level
    reward = {
        "pool": "rare" if is_rare else "common",
        "level": level,
        "base_level": base_level,
        "allowed_types": allowed_types,
        "rare": is_rare,
        "source": "backend_roll",
        "reward_difficulty": personal_scale,
        "critical_success_rare_upgrade_chance": (
            DEADLY_TRIAL_CRITICAL_RARE_UPGRADE_CHANCE if is_deadly else MISSION_CRITICAL_RARE_UPGRADE_CHANCE
        ),
        "critical_success_rare_upgrade_allowed_types": list(RARE_REWARD_TYPES),
        "instruction": (
            "Choose the reward type from allowed_types by the character action and mission context. "
            "Keep this level for a full contribution; on critical_success a strong contribution improves "
            "leveled or gold rewards by 20%; stat is always +1. "
            "If critical_success_rare_upgrade_chance is used for a logic_tier 3 contribution, Codex may mark "
            "the reward change with source=critical_rare_upgrade and choose from "
            "critical_success_rare_upgrade_allowed_types instead of allowed_types. "
            "Use only if this character made a full contribution to a successful mission."
        ),
    }
    _maybe_apply_titled_reward(reward, is_deadly, rng)
    return reward


def roll_boss_final_reward(mission_difficulty: int) -> dict[str, Any]:
    rng = random.SystemRandom()
    level = _roll_level_in_bounds(rng, boss_final_reward_level_bounds(mission_difficulty))
    return {
        "pool": "boss_final",
        "level": level,
        "base_level": level,
        "allowed_types": list(BOSS_FINAL_REWARD_TYPES),
        "rare": True,
        "source": "backend_boss_final_roll",
        "stat_delta": level,
        "instruction": (
            "Guaranteed meaningful final phased boss reward. Choose inventory, spells, stat, pet, companion "
            "or mount by the character action and boss context; never choose gold. Keep this level for leveled "
            "rewards; stat delta equals stat_delta. Give this reward to every participant if the final phase is completed."
        ),
    }


def boss_final_reward_level_bounds(mission_difficulty: int) -> tuple[int, int]:
    return _scaled_reward_bounds(mission_difficulty, BOSS_FINAL_REWARD_DIVISOR)


def boss_trophy_level_bounds(mission_difficulty: int) -> tuple[int, int]:
    return _scaled_reward_bounds(mission_difficulty, BOSS_TROPHY_REWARD_DIVISOR)


def _scaled_reward_bounds(mission_difficulty: int, divisor: int) -> tuple[int, int]:
    center = max(1.0, int(mission_difficulty) / max(1, divisor))
    min_level = max(1, math.floor(center * (1 - BOSS_REWARD_VARIANCE)))
    max_level = max(min_level, math.ceil(center * (1 + BOSS_REWARD_VARIANCE)))
    return min_level, max_level


def _roll_level_in_bounds(rng: random.SystemRandom, bounds: tuple[int, int]) -> int:
    min_level, max_level = bounds
    return rng.randint(int(min_level), int(max_level))


def _maybe_apply_titled_reward(
    reward: dict[str, Any],
    is_deadly_trial: bool,
    rng: random.Random | random.SystemRandom,
) -> None:
    if not is_deadly_trial:
        return
    if rng.random() >= DEADLY_TRIAL_TITLED_REWARD_CHANCE:
        return
    eligible = [
        reward_type for reward_type in reward.get("allowed_types", [])
        if reward_type in DEADLY_TRIAL_TITLED_TYPES
    ]
    if not eligible:
        return
    reward["titled_reward"] = {
        "rank": "titled",
        "exclusive": MISSION_TYPE_DEADLY_TRIAL,
        "eligible_types": eligible,
        "instruction": (
            "If the chosen reward type is one of eligible_types, create a titled entity with a strong title "
            "that matches the deadly_trial context."
        ),
    }


def _roll_reward_level(rng: random.SystemRandom, mission_difficulty: int) -> int:
    min_level, max_level = reward_level_bounds(mission_difficulty)
    levels = list(range(min_level, max_level + 1))
    if len(levels) <= 1:
        return levels[0]

    roll = rng.random()
    lower_end = max(1, len(levels) // 3)
    middle_end = max(lower_end + 1, (len(levels) * 2) // 3)
    if roll < 0.60:
        bucket = levels[:lower_end]
    elif roll < 0.90:
        bucket = levels[lower_end:middle_end]
    else:
        bucket = levels[middle_end:]
    return rng.choice(bucket or levels)


def recommended_mission_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS count FROM characters WHERE is_active = 1").fetchone()
    character_count = int(row["count"]) if row else 0
    if character_count <= 0:
        return MIN_MISSIONS_PER_TURN
    return max(MIN_MISSIONS_PER_TURN, (character_count + MISSION_MAX_PARTICIPANTS - 1) // MISSION_MAX_PARTICIPANTS)


def reward_level_bounds(mission_difficulty: int) -> tuple[int, int]:
    return max(1, int(mission_difficulty) // 3), int(mission_difficulty)


def _reward_roll_for_mission(
    mission: dict[str, Any],
    character: dict[str, Any] | None = None,
    turn_id: int | None = None,
) -> dict[str, Any]:
    if mission_is_phased_boss(mission) and int(mission.get("phase", 1)) >= int(mission.get("max_phase", 1)):
        return roll_boss_final_reward(int(mission["difficulty"]))
    mission_share = (
        int(mission["difficulty"])
        if mission_is_phased_boss(mission)
        else personal_difficulty_share(int(mission["difficulty"]))
    )
    personal_cap = character_power_rating(character, turn_id) if character is not None else mission_share
    reward_difficulty = min(mission_share, personal_cap)
    return roll_reward(
        int(mission["difficulty"]),
        mission.get("mission_type"),
        reward_difficulty=reward_difficulty,
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _tanellorn_lore_terms() -> tuple[str, ...]:
    root = _project_root()
    files = [
        root / "tanellorn_lore.md",
        root / "tanellorn_lore.js",
        root / "lore" / "tanellorn_lore.md",
        root / "lore" / "tanellorn_lore.js",
    ]
    files.extend(sorted((root / "lore").glob("*.md")))
    terms: set[str] = {
        "Танелорн",
        "Город Порогов",
        "Город Долгов",
        "Каменный Улей",
        "Каррок Манор",
        "Госпожа",
        "Магистрат",
        "Канцелярия Порогов",
        "Совет Гильдий",
        "Квартал Старых Гнезд",
        "Улица Дырявой Башни",
        "Канцелярский Склон",
        "Рынок Неверных Ключей",
        "Нижние Лестницы",
        "Сектор Семи Вывесок",
        "Мост Спящих Нотариусов",
        "Площадь Второго Завтра",
        "Переулок Слепых Фонарей",
        "Стекольные Ярусы",
        "Карман Тихой Прачечной",
        "Гнилой Балкон",
        "Сад Неподписанных Договоров",
        "Пристань Сухой Воды",
        "Арка Тысячи Долгов",
    }
    ignored = {
        "Танелорн",
        "Основные Черты Города",
        "Тон Для Миссий",
        "Визуальные Мотивы",
        "Запреты Для Генерации",
        "Примеры Названий",
        "Принцип Районов",
    }
    for path in files:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for quoted in re.findall(r"['\"]([^'\"]{4,80}[А-Яа-яЁё][^'\"]{0,80})['\"]", text):
            _add_lore_term(terms, quoted, ignored)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                _add_lore_term(terms, stripped.lstrip("#").strip(), ignored)
            elif stripped.startswith("- "):
                candidate = re.split(r"\s[-—:]\s|[.;]", stripped[2:].strip(), maxsplit=1)[0]
                _add_lore_term(terms, candidate, ignored)
    return tuple(sorted(terms, key=lambda value: (-len(value), value.casefold())))


def _add_lore_term(terms: set[str], value: str, ignored: set[str]) -> None:
    term = " ".join(str(value or "").strip().strip("`*_").split())
    if not term or term in ignored:
        return
    words = term.split()
    if len(term) < 4 or len(term) > 80 or len(words) > 6:
        return
    if not re.search(r"[А-ЯЁA-Z]", term):
        return
    if term.casefold() in {"город", "районы", "история", "магия", "экономика", "гильдии"}:
        return
    terms.add(term)


def _free_action_lore_matches(action_text: str) -> list[str]:
    folded = f" {action_text.casefold()} "
    matches: list[str] = []
    for term in _tanellorn_lore_terms():
        if term.casefold() in folded:
            matches.append(term)
        if len(matches) >= 5:
            break
    return matches


def _reward_roll_for_free_action(
    character: dict[str, Any], turn_id: int | None = None, action_text: str = ""
) -> dict[str, Any]:
    rng = random.SystemRandom()
    readiness = max(1, character_power_rating(character, turn_id))
    reward_difficulty = max(1, math.ceil(readiness * 0.75))
    lore_matches = _free_action_lore_matches(action_text)
    lore_bonus = bool(lore_matches)
    rare_chance = FREE_ACTION_LORE_RARE_REWARD_CHANCE if lore_bonus else FREE_ACTION_RARE_REWARD_CHANCE
    is_rare = rng.random() < rare_chance
    allowed_types = list(RARE_REWARD_TYPES if is_rare else COMMON_REWARD_TYPES)
    raw_level = _roll_reward_level(rng, reward_difficulty)
    base_level = raw_level + FREE_ACTION_LORE_LEVEL_BONUS if lore_bonus else raw_level
    return {
        "pool": "rare" if is_rare else "common",
        "level": base_level,
        "base_level": raw_level,
        "allowed_types": allowed_types,
        "rare": is_rare,
        "source": "backend_free_action_roll",
        "reward_difficulty": reward_difficulty,
        "rare_chance": rare_chance,
        "lore_reference_bonus": lore_bonus,
        "lore_matches": lore_matches,
        "instruction": (
            "Use for a meaningful free action when the reward follows the player's intention, tone, stats, assets, "
            "and scene. Free actions may grant pleasant medium rewards, personal progress, contacts, improvements, "
            "states, clues, gold, or story hooks. Choose the concrete type from allowed_types by the action context. "
            "If lore_reference_bonus is true, favor a positive world response when the lore reference is used logically."
        ),
    }


def create_character(
    conn: sqlite3.Connection,
    telegram_id: int,
    name: str,
    gender: str,
    race: str,
    description: str = "",
    stats: dict[str, int] | None = None,
    starter_spell: str = "",
    starter_items: list[str] | None = None,
) -> dict[str, Any]:
    player = get_player(conn, telegram_id)
    if player is None:
        raise ValueError("Сначала отправь /start.")
    existing = row_to_dict(
        conn.execute("SELECT * FROM characters WHERE player_id = ? AND is_active = 1", (player["id"],)).fetchone()
    )
    if existing:
        raise ValueError(
            f"У тебя уже есть персонаж: {existing['name']}. "
            "В альфе повторное создание отключено. Если нужно что-то исправить, скажи мастеру."
        )

    name = name.strip()
    gender = gender.strip()
    race = race.strip()
    description = description.strip()

    _validate_text_length(name, "Имя героя", 1, CHARACTER_NAME_MAX_LENGTH)
    _validate_text_length(gender, "Пол", 1, CHARACTER_FIELD_MAX_LENGTH)
    _validate_text_length(race, "Раса", 1, CHARACTER_FIELD_MAX_LENGTH)
    _validate_text_length(
        description,
        "Описание героя",
        CHARACTER_DESCRIPTION_MIN_LENGTH,
        CHARACTER_DESCRIPTION_MAX_LENGTH,
    )
    _validate_character_name_available(conn, telegram_id, name)

    normalized_stats = normalize_stats(stats)
    normalized_spells = normalize_starter_spell(starter_spell)
    normalized_inventory = normalize_starter_items(starter_items or [])
    _validate_unique_names([starter_spell, *[item["name"] for item in normalized_inventory]])
    conn.execute(
        """
        INSERT INTO characters (
            player_id,
            name,
            gender,
            race,
            description,
            stats_json,
            spells_json,
            skills_json,
            traits_json,
            inventory_json,
            pet_json,
            companion_json,
            mount_json,
            pets_json,
            companions_json,
            mounts_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            player["id"],
            name,
            gender,
            race,
            description,
            to_json(normalized_stats),
            to_json(normalized_spells),
            to_json([]),
            to_json([]),
            to_json(normalized_inventory),
            None,
            None,
            None,
            to_json([]),
            to_json([]),
            to_json([]),
        ),
    )
    conn.commit()
    character = get_character_for_player(conn, telegram_id)
    if character is None:
        raise RuntimeError("Не удалось создать персонажа.")
    return character


def restore_character_from_payload(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    character_payload = payload["character"]
    telegram_id = int(character_payload["telegram_id"])
    username = str(character_payload.get("username") or "").strip() or None
    notify_enabled = bool(character_payload.get("notify_enabled", True))
    player = upsert_player(conn, telegram_id, username, notify_enabled=notify_enabled)

    name = str(character_payload["name"]).strip()
    gender = str(character_payload["gender"]).strip()
    race = str(character_payload["race"]).strip()
    description = str(character_payload["description"]).strip()
    level = int(character_payload["level"])
    xp = int(character_payload.get("xp", 0))
    gold = int(character_payload.get("gold", 0))

    _validate_text_length(name, "Имя героя", 1, CHARACTER_NAME_MAX_LENGTH)
    _validate_text_length(gender, "Пол", 1, CHARACTER_FIELD_MAX_LENGTH)
    _validate_text_length(race, "Раса", 1, CHARACTER_FIELD_MAX_LENGTH)
    _validate_text_length(description, "Описание героя", CHARACTER_DESCRIPTION_MIN_LENGTH, CHARACTER_DESCRIPTION_MAX_LENGTH)

    normalized_stats = normalize_stats(character_payload.get("stats"), require_exact_total=False)
    normalized_spells = _normalize_restore_named_assets(character_payload.get("spells", []), asset_label="заклинание", with_uid=False)
    normalized_inventory = _normalize_restore_named_assets(character_payload.get("inventory", []), asset_label="предмет", with_uid=True)
    normalized_pets = _normalize_restore_entities(character_payload.get("pets", []), entity_label="питомец")
    normalized_companions = _normalize_restore_entities(character_payload.get("companions", []), entity_label="спутник")
    normalized_mounts = _normalize_restore_entities(character_payload.get("mounts", []), entity_label="маунт")
    normalized_status = _normalize_restore_status(character_payload.get("status", {}))

    _validate_character_name_available(conn, telegram_id, name)
    _validate_unique_names(
        [
            *[item["name"] for item in normalized_inventory],
            *[spell["name"] for spell in normalized_spells],
            *[entity["name"] for entity in normalized_pets],
            *[entity["name"] for entity in normalized_companions],
            *[entity["name"] for entity in normalized_mounts],
        ]
    )

    existing = row_to_dict(
        conn.execute("SELECT * FROM characters WHERE player_id = ? AND is_active = 1", (player["id"],)).fetchone()
    )
    if existing:
        conn.execute(
            """
            UPDATE characters
            SET name = ?, gender = ?, race = ?, description = ?, is_active = 1, level = ?, xp = ?, gold = ?,
                stats_json = ?, spells_json = ?, inventory_json = ?, pets_json = ?, companions_json = ?, mounts_json = ?,
                pet_json = NULL, companion_json = NULL, mount_json = NULL,
                status_json = ?
            WHERE player_id = ?
            """,
            (
                name,
                gender,
                race,
                description,
                level,
                xp,
                gold,
                to_json(normalized_stats),
                to_json(normalized_spells),
                to_json(normalized_inventory),
                to_json(normalized_pets),
                to_json(normalized_companions),
                to_json(normalized_mounts),
                to_json(normalized_status),
                player["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO characters (
                player_id, name, gender, race, description, level, xp, gold,
                stats_json, spells_json, skills_json, traits_json, inventory_json,
                pet_json, companion_json, mount_json,
                pets_json, companions_json, mounts_json, status_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                player["id"],
                name,
                gender,
                race,
                description,
                level,
                xp,
                gold,
                to_json(normalized_stats),
                to_json(normalized_spells),
                to_json([]),
                to_json([]),
                to_json(normalized_inventory),
                to_json(normalized_pets),
                to_json(normalized_companions),
                to_json(normalized_mounts),
                to_json(normalized_status),
            ),
        )

    conn.commit()
    restored = get_character_for_player(conn, telegram_id)
    if restored is None:
        raise RuntimeError("Не удалось восстановить персонажа.")
    return restored


def create_turn_from_payload(conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
    turn = payload["turn"]
    missions = payload["missions"]
    art = _turn_art_payload(turn)

    validate_turn_for_current_roster(conn, payload)

    open_turn = get_open_turn(conn)
    if open_turn:
        raise ValueError(f"Уже есть открытый ход #{open_turn['id']}: {open_turn['title']}")

    cur = conn.execute(
        """
        INSERT INTO turns (title, deadline, art_prompt, art_caption, status)
        VALUES (?, ?, ?, ?, 'open')
        """,
        (turn["title"], turn.get("deadline"), art.get("prompt"), art.get("caption")),
    )
    turn_id = int(cur.lastrowid)

    for mission in missions:
        _insert_mission(conn, turn_id, mission)
    _carry_unresolved_board_missions_to_turn(conn, turn_id)
    _carry_locked_participants_to_new_turn(conn, turn_id)
    refresh_shop_for_new_turn(conn)
    conn.commit()
    return turn_id


def append_missions_to_open_turn(conn: sqlite3.Connection, missions: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    open_turn = get_open_turn(conn)
    if not open_turn:
        raise ValueError("Открытого хода нет.")

    validate_mission_additions_for_current_roster(conn, missions)
    created: list[dict[str, Any]] = []
    for mission in missions:
        mission_id = _insert_mission(conn, int(open_turn["id"]), mission)
        row = conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
        created.append(row_to_dict(row) or {})
    conn.commit()
    return open_turn, created


def _insert_mission(conn: sqlite3.Connection, turn_id: int, mission: dict[str, Any]) -> int:
    mission_type = _normalize_mission_type(mission.get("type"))
    mission_subtype = _normalize_mission_subtype(mission.get("subtype"))
    phase = int(mission.get("phase", 1))
    max_phase = int(mission.get("max_phase", 1))
    max_participants = int(
        mission.get(
            "max_participants",
            BOSS_MAX_PARTICIPANTS if mission_type == MISSION_TYPE_BOSS else MISSION_MAX_PARTICIPANTS,
        )
    )
    party_locked = bool(mission.get("party_locked", mission_type == MISSION_TYPE_BOSS and mission_subtype == "phased"))
    lock_warning = str(mission.get("lock_warning") or "").strip() or (
        "Вступив в бой, герой останется в нем до победы или поражения."
        if party_locked and mission_type == MISSION_TYPE_BOSS and mission_subtype == "phased"
        else "При смертельном провале герой может погибнуть или переродиться."
        if mission_type == MISSION_TYPE_DEADLY_TRIAL
        else ""
    )
    continuation_key = str(mission.get("continuation_key") or "").strip() or None
    boss_name = str(mission.get("boss_name") or "").strip() or None
    boss_theme = str(mission.get("boss_theme") or "").strip() or None
    cur = conn.execute(
        """
        INSERT INTO missions (
            turn_id, title, description, mission_type, mission_subtype, phase, max_phase,
            max_participants, party_locked, lock_warning, continuation_key, boss_name, boss_theme,
            difficulty, status, threat_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """,
        (
            turn_id,
            mission["title"],
            mission["description"],
            mission_type,
            mission_subtype,
            phase,
            max_phase,
            max_participants,
            int(party_locked),
            lock_warning or None,
            continuation_key,
            boss_name,
            boss_theme,
            int(mission.get("difficulty", 1)),
            to_json(mission.get("threat", {})),
        ),
    )
    return int(cur.lastrowid)


def _carry_unresolved_board_missions_to_turn(conn: sqlite3.Connection, turn_id: int) -> list[int]:
    rows = conn.execute(
        """
        SELECT *
        FROM missions
        WHERE turn_id <> ?
          AND status IN ('open', 'ongoing')
          AND COALESCE(carried_to_mission_id, 0) = 0
          AND NOT (mission_type = ? AND mission_subtype = 'phased' AND party_locked = 1)
        ORDER BY id
        """,
        (turn_id, MISSION_TYPE_BOSS),
    ).fetchall()
    carried_ids: list[int] = []
    for row in rows:
        source = row_to_dict(row) or {}
        cur = conn.execute(
            """
            INSERT INTO missions (
                turn_id, title, description, mission_type, mission_subtype, phase, max_phase,
                max_participants, party_locked, lock_warning, continuation_key, boss_name, boss_theme,
                difficulty, status, threat_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_id,
                source["title"],
                source["description"],
                source.get("mission_type") or MISSION_TYPE_STANDARD,
                source.get("mission_subtype"),
                int(source.get("phase", 1)),
                int(source.get("max_phase", 1)),
                int(source.get("max_participants", MISSION_MAX_PARTICIPANTS)),
                int(source.get("party_locked", 0) or 0),
                source.get("lock_warning"),
                source.get("continuation_key"),
                source.get("boss_name"),
                source.get("boss_theme"),
                int(source.get("difficulty", 1)),
                source.get("status") or "open",
                source.get("threat_json") or "{}",
            ),
        )
        new_id = int(cur.lastrowid)
        conn.execute("UPDATE missions SET carried_to_mission_id = ? WHERE id = ?", (new_id, int(source["id"])))
        carried_ids.append(new_id)
    return carried_ids


def _turn_art_payload(turn: dict[str, Any]) -> dict[str, str | None]:
    art = turn.get("art") if isinstance(turn.get("art"), dict) else {}
    prompt = art.get("prompt") or turn.get("art_prompt")
    caption = art.get("caption") or turn.get("art_caption")
    return {
        "prompt": str(prompt).strip() if prompt else None,
        "caption": str(caption).strip() if caption else None,
    }


def set_turn_art(conn: sqlite3.Connection, turn_id: int, file_id: str, caption: str | None = None) -> None:
    conn.execute(
        "UPDATE turns SET art_file_id = ?, art_caption = COALESCE(?, art_caption) WHERE id = ?",
        (file_id, caption, turn_id),
    )
    conn.commit()


def validate_turn_for_current_roster(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    missions = payload["missions"]
    carry_only = bool(payload.get("carry_unresolved_only") is True or payload.get("turn", {}).get("carry_unresolved_only") is True)
    if carry_only and not missions:
        unresolved_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM missions
            WHERE status IN ('open', 'ongoing')
              AND COALESCE(carried_to_mission_id, 0) = 0
              AND NOT (mission_type = ? AND mission_subtype = 'phased' AND party_locked = 1)
            """,
            (MISSION_TYPE_BOSS,),
        ).fetchone()["count"]
        if int(unresolved_count) <= 0:
            raise ValueError("Для carry_unresolved_only нет открытых миссий для переноса.")
        return
    if count_limit_missions(missions) < MIN_MISSIONS_PER_TURN:
        raise ValueError(f"В ходе должно быть не меньше {MIN_MISSIONS_PER_TURN} миссий без учета deadly_trial.")
    validate_mission_additions_for_current_roster(conn, missions)


def count_limit_missions(missions: list[dict[str, Any]]) -> int:
    return sum(
        1
        for mission in missions
        if _normalize_mission_type(mission.get("type") or mission.get("mission_type")) != MISSION_TYPE_DEADLY_TRIAL
    )


def validate_mission_additions_for_current_roster(conn: sqlite3.Connection, missions: list[dict[str, Any]]) -> None:
    bounds = mission_difficulty_bounds(conn)
    if bounds is None:
        return

    min_difficulty, max_difficulty = bounds
    upper_quartile = _upper_quartile_power(conn)
    deadly_difficulty = deadly_trial_difficulty(upper_quartile or 1)
    for index, mission in enumerate(missions, start=1):
        mission_type = _normalize_mission_type(mission.get("type") or mission.get("mission_type"))
        difficulty = int(mission.get("difficulty", 1))
        if mission_type == MISSION_TYPE_DEADLY_TRIAL:
            if difficulty != deadly_difficulty:
                raise ValueError(
                    f"Сложность deadly_trial миссии #{index} должна быть {deadly_difficulty} "
                    f"(round({upper_quartile} * {DEADLY_TRIAL_DIFFICULTY_MULTIPLIER}) по верхнему квартилю ростера)."
                )
            continue
        if mission_type == MISSION_TYPE_BOSS and str(mission.get("subtype") or mission.get("mission_subtype") or "").strip().lower() == "phased":
            max_participants = int(mission.get("max_participants", BOSS_MAX_PARTICIPANTS))
            boss_max_difficulty = party_difficulty_ceiling(conn, max_participants) or max_difficulty
            if difficulty < min_difficulty or difficulty > boss_max_difficulty:
                raise ValueError(
                    f"Сложность boss-миссии #{index} должна быть от {min_difficulty} до {boss_max_difficulty} "
                    f"по суммарной доступной мощности участников босса."
                )
            continue
        if difficulty < min_difficulty or difficulty > max_difficulty:
            raise ValueError(
                f"Сложность миссии #{index} должна быть от {min_difficulty} до {max_difficulty} "
                f"по суммарной мощности группы до {MISSION_MAX_PARTICIPANTS} героев."
            )


def get_open_turn(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM turns WHERE status = 'open' ORDER BY id DESC LIMIT 1").fetchone()
    return row_to_dict(row)


def get_turn(conn: sqlite3.Connection, turn_id: int) -> dict[str, Any] | None:
    return row_to_dict(conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone())


def list_open_missions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    turn = get_open_turn(conn)
    if not turn:
        return []
    rows = conn.execute(
        "SELECT * FROM missions WHERE turn_id = ? AND status IN ('open', 'ongoing') ORDER BY id",
        (turn["id"],),
    ).fetchall()
    return with_public_difficulty_labels([row_to_dict(row) or {} for row in rows], mission_difficulty_bounds(conn))


TANELLORN_MAP_POSITIONS = (
    (47, 41),
    (28, 59),
    (22, 38),
    (72, 39),
    (72, 63),
    (42, 72),
    (47, 25),
    (56, 56),
)


def build_tanellorn_map_state(conn: sqlite3.Connection) -> dict[str, Any]:
    turn = get_open_turn(conn)
    missions = list_open_missions(conn)
    mapped_missions: list[dict[str, Any]] = []
    for index, mission in enumerate(missions):
        position = TANELLORN_MAP_POSITIONS[index % len(TANELLORN_MAP_POSITIONS)]
        participant_count = _mission_action_count(conn, int(mission["id"]), int(mission["turn_id"]))
        mapped_missions.append(
            {
                "id": int(mission["id"]),
                "title": str(mission["title"]),
                "difficulty_label": mission.get("difficulty_label")
                or mission_difficulty_label(
                    int(mission["difficulty"]),
                    mission_difficulty_bounds(conn),
                    mission.get("mission_type"),
                ),
                "description": str(mission["description"]),
                "x": position[0],
                "y": position[1],
                "participants_count": int(participant_count),
                "participants_limit": mission_max_participants(mission),
                "status": str(mission["status"]),
                "type": str(mission.get("mission_type") or MISSION_TYPE_STANDARD),
                "subtype": mission.get("mission_subtype"),
            }
        )
    return {
        "mode": "tanellorn_map_v1",
        "turn": (
            {"id": int(turn["id"]), "title": str(turn["title"]), "deadline": turn.get("deadline")}
            if turn
            else None
        ),
        "missions": mapped_missions,
    }


def _normalize_mission_type(value: Any) -> str:
    mission_type = str(value or "standard").strip().lower()
    return mission_type if mission_type in {MISSION_TYPE_STANDARD, MISSION_TYPE_BOSS, MISSION_TYPE_DEADLY_TRIAL} else MISSION_TYPE_STANDARD


def _normalize_mission_subtype(value: Any) -> str | None:
    subtype = str(value or "").strip().lower()
    return subtype or None


def mission_is_locked(mission: dict[str, Any]) -> bool:
    return bool(mission.get("party_locked"))


def mission_max_participants(mission: dict[str, Any]) -> int:
    default = BOSS_MAX_PARTICIPANTS if _normalize_mission_type(mission.get("mission_type") or mission.get("type")) == MISSION_TYPE_BOSS else MISSION_MAX_PARTICIPANTS
    try:
        value = int(mission.get("max_participants", default))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def mission_is_phased_boss(mission: dict[str, Any]) -> bool:
    mission_type = _normalize_mission_type(mission.get("mission_type") or mission.get("type"))
    mission_subtype = _normalize_mission_subtype(mission.get("mission_subtype") or mission.get("subtype"))
    return mission_type == MISSION_TYPE_BOSS and mission_subtype == "phased"


def _mission_action_count(conn: sqlite3.Connection, mission_id: int, turn_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT actions.character_id) AS count
            FROM actions
            WHERE actions.turn_id = ?
              AND actions.mission_id = ?
            """,
            (turn_id, mission_id),
        ).fetchone()["count"]
    )


def _mission_action_character_ids(conn: sqlite3.Connection, mission_id: int, turn_id: int) -> set[int]:
    rows = conn.execute(
        """
        SELECT DISTINCT actions.character_id
        FROM actions
        WHERE actions.turn_id = ?
          AND actions.mission_id = ?
        ORDER BY actions.character_id
        """,
        (turn_id, mission_id),
    ).fetchall()
    return {int(row["character_id"]) for row in rows}


def _carry_locked_participants_to_new_turn(conn: sqlite3.Connection, turn_id: int) -> None:
    mission_rows = conn.execute(
        "SELECT * FROM missions WHERE turn_id = ? AND party_locked = 1 AND continuation_key IS NOT NULL ORDER BY id",
        (turn_id,),
    ).fetchall()
    for row in mission_rows:
        mission = row_to_dict(row) or {}
        continuation_key = str(mission.get("continuation_key") or "").strip()
        if not continuation_key:
            continue
        source = conn.execute(
            """
            SELECT *
            FROM missions
            WHERE continuation_key = ?
              AND party_locked = 1
              AND turn_id <> ?
              AND status = 'ongoing'
            ORDER BY turn_id DESC, id DESC
            LIMIT 1
            """,
            (continuation_key, turn_id),
        ).fetchone()
        if not source:
            continue
        participant_ids = _mission_action_character_ids(conn, int(source["id"]), int(source["turn_id"]))
        for character_id in participant_ids:
            conn.execute(
                """
                INSERT INTO mission_participants (mission_id, character_id)
                VALUES (?, ?)
                ON CONFLICT(mission_id, character_id) DO NOTHING
                """,
                (int(mission["id"]), character_id),
            )


def join_mission(conn: sqlite3.Connection, telegram_id: int, mission_id: int) -> dict[str, Any]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа: /create_character Имя | Пол | Раса | описание | характеристики | заклинание | 3 предмета")

    mission = row_to_dict(conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone())
    if not mission or mission["status"] not in {"open", "ongoing"}:
        raise ValueError("Такой открытой миссии нет.")

    turn = get_open_turn(conn)
    if not turn or mission["turn_id"] != turn["id"]:
        raise ValueError("Эта миссия не относится к текущему открытому ходу.")

    joined_mission = conn.execute(
        """
        SELECT missions.id, missions.title, missions.party_locked, missions.mission_type, missions.mission_subtype
        FROM mission_participants
        JOIN missions ON missions.id = mission_participants.mission_id
        WHERE mission_participants.character_id = ?
          AND missions.turn_id = ?
        ORDER BY mission_participants.joined_at DESC
        LIMIT 1
        """,
        (character["id"], turn["id"]),
    ).fetchone()

    joined_mission_dict = row_to_dict(joined_mission)
    if joined_mission_dict and int(joined_mission_dict["id"]) != mission_id and mission_is_locked(joined_mission_dict):
        raise ValueError(
            f"Ты уже вступил в миссию #{joined_mission_dict['id']} «{joined_mission_dict['title']}» и не можешь покинуть ее, "
            "пока бой не завершится победой или поражением."
        )

    participant_count = _mission_action_count(conn, mission_id, int(turn["id"]))
    already_joined = conn.execute(
        "SELECT 1 FROM mission_participants WHERE mission_id = ? AND character_id = ?",
        (mission_id, character["id"]),
    ).fetchone()
    max_participants = mission_max_participants(mission)
    if participant_count >= max_participants and not already_joined:
        raise ValueError(f"На миссии уже максимум участников: {max_participants}.")

    switched_from: dict[str, Any] | None = None
    action_cleared = False
    if joined_mission and int(joined_mission["id"]) != mission_id:
        switched_from = {"id": int(joined_mission["id"]), "title": str(joined_mission["title"])}
        conn.execute(
            """
            DELETE FROM mission_participants
            WHERE mission_id = ? AND character_id = ?
            """,
            (joined_mission["id"], character["id"]),
        )
        deleted_actions = conn.execute(
            """
            DELETE FROM actions
            WHERE turn_id = ? AND mission_id = ? AND character_id = ?
            """,
            (turn["id"], joined_mission["id"], character["id"]),
        ).rowcount
        action_cleared = deleted_actions > 0

    conn.execute(
        """
        INSERT INTO mission_participants (mission_id, character_id)
        VALUES (?, ?)
        ON CONFLICT(mission_id, character_id) DO NOTHING
        """,
        (mission_id, character["id"]),
    )
    conn.execute(
        "DELETE FROM free_actions WHERE turn_id = ? AND character_id = ?",
        (turn["id"], character["id"]),
    )
    conn.commit()
    mission["switched_from"] = switched_from
    mission["action_cleared"] = action_cleared
    return mission


def submit_action(conn: sqlite3.Connection, telegram_id: int, action_text: str) -> dict[str, Any]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа: /create_character Имя | Пол | Раса | описание | характеристики | заклинание | 3 предмета")

    turn = get_open_turn(conn)
    if not turn:
        raise ValueError("Сейчас нет открытого хода.")

    mission = conn.execute(
        """
        SELECT missions.*
        FROM missions
        JOIN mission_participants ON mission_participants.mission_id = missions.id
        WHERE mission_participants.character_id = ?
          AND missions.turn_id = ?
        ORDER BY mission_participants.joined_at DESC
        LIMIT 1
        """,
        (character["id"], turn["id"]),
    ).fetchone()
    if not mission:
        raise ValueError("Сначала выбери миссию: /join <id>")

    validate_action_text(action_text)

    active_action_count = _mission_action_count(conn, int(mission["id"]), int(turn["id"]))
    already_submitted = conn.execute(
        """
        SELECT 1 FROM actions
        WHERE turn_id = ? AND mission_id = ? AND character_id = ?
        """,
        (turn["id"], mission["id"], character["id"]),
    ).fetchone()
    max_participants = mission_max_participants(row_to_dict(mission) or {})
    if active_action_count >= max_participants and not already_submitted:
        raise ValueError(f"На миссии уже максимум участников с отправленным ходом: {max_participants}.")

    conn.execute(
        """
        INSERT INTO actions (turn_id, mission_id, character_id, action_text)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(turn_id, mission_id, character_id) DO UPDATE SET
            action_text = excluded.action_text,
            submitted_at = CURRENT_TIMESTAMP
        """,
        (turn["id"], mission["id"], character["id"], action_text),
    )
    conn.commit()
    return row_to_dict(mission) or {}


def submit_free_action(conn: sqlite3.Connection, telegram_id: int, action_text: str) -> dict[str, Any]:
    character = get_character_for_player(conn, telegram_id)
    if not character:
        raise ValueError("Сначала создай персонажа: /create_character Имя | Пол | Раса | описание | характеристики | заклинание | 3 предмета")

    turn = get_open_turn(conn)
    if not turn:
        raise ValueError("Сейчас нет открытого хода.")

    validate_action_text(action_text)

    locked_mission = conn.execute(
        """
        SELECT missions.id, missions.title
        FROM mission_participants
        JOIN missions ON missions.id = mission_participants.mission_id
        WHERE mission_participants.character_id = ?
          AND missions.turn_id = ?
          AND missions.party_locked = 1
        LIMIT 1
        """,
        (character["id"], turn["id"]),
    ).fetchone()
    if locked_mission:
        raise ValueError(
            f"Герой закреплен в миссии #{locked_mission['id']} «{locked_mission['title']}» до ее завершения."
        )

    joined_rows = conn.execute(
        """
        SELECT missions.id
        FROM mission_participants
        JOIN missions ON missions.id = mission_participants.mission_id
        WHERE mission_participants.character_id = ?
          AND missions.turn_id = ?
        """,
        (character["id"], turn["id"]),
    ).fetchall()
    for row in joined_rows:
        conn.execute(
            "DELETE FROM actions WHERE turn_id = ? AND mission_id = ? AND character_id = ?",
            (turn["id"], int(row["id"]), character["id"]),
        )
        conn.execute(
            "DELETE FROM mission_participants WHERE mission_id = ? AND character_id = ?",
            (int(row["id"]), character["id"]),
        )

    conn.execute(
        """
        INSERT INTO free_actions (turn_id, character_id, action_text)
        VALUES (?, ?, ?)
        ON CONFLICT(turn_id, character_id) DO UPDATE SET
            action_text = excluded.action_text,
            submitted_at = CURRENT_TIMESTAMP
        """,
        (turn["id"], character["id"], action_text),
    )
    conn.commit()
    return {"turn": turn, "character": character}


def current_free_action_for_player(conn: sqlite3.Connection, telegram_id: int) -> dict[str, Any] | None:
    turn = get_open_turn(conn)
    if not turn:
        return None
    row = conn.execute(
        """
        SELECT
            free_actions.*,
            turns.title AS turn_title,
            turns.deadline,
            characters.name AS character_name
        FROM free_actions
        JOIN turns ON turns.id = free_actions.turn_id
        JOIN characters ON characters.id = free_actions.character_id
        JOIN players ON players.id = characters.player_id
        WHERE free_actions.turn_id = ?
          AND players.telegram_id = ?
        LIMIT 1
        """,
        (turn["id"], telegram_id),
    ).fetchone()
    return row_to_dict(row)


def validate_action_text(action_text: str) -> None:
    text = action_text.strip()
    _validate_text_length(text, "Текст хода", ACTION_TEXT_MIN_LENGTH, ACTION_TEXT_MAX_LENGTH)

    long_tokens = [token for token in text.replace("\n", " ").split() if len(token) >= 40]
    if long_tokens:
        raise ValueError(
            "В ходе есть слишком длинные куски текста без пробелов. Похоже на сломанную вставку или билиберду, "
            "попробуй переписать аккуратнее."
        )


def close_turn(conn: sqlite3.Connection, turn_id: int) -> None:
    conn.execute("UPDATE turns SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE id = ?", (turn_id,))
    conn.commit()


def build_turn_export(conn: sqlite3.Connection, turn_id: int) -> dict[str, Any]:
    turn = get_turn(conn, turn_id)
    if not turn:
        raise ValueError(f"Ход #{turn_id} не найден.")

    mission_rows = conn.execute("SELECT * FROM missions WHERE turn_id = ? ORDER BY id", (turn_id,)).fetchall()
    missions: list[dict[str, Any]] = []

    for mission_row in mission_rows:
        mission = row_to_dict(mission_row) or {}
        participant_rows = conn.execute(
            """
            SELECT
                characters.*,
                players.telegram_id,
                players.username,
                actions.action_text
            FROM mission_participants
            JOIN characters ON characters.id = mission_participants.character_id
            JOIN players ON players.id = characters.player_id
            JOIN actions
                ON actions.character_id = characters.id
               AND actions.mission_id = mission_participants.mission_id
               AND actions.turn_id = ?
            WHERE mission_participants.mission_id = ?
            ORDER BY characters.id
            """,
            (turn_id, mission["id"]),
        ).fetchall()

        participants: list[dict[str, Any]] = []
        for row in participant_rows:
            character = row_to_dict(row) or {}
            participants.append(
                {
                    "character_id": character["id"],
                    "telegram_id": character["telegram_id"],
                    "username": character["username"],
                    "name": character["name"],
                    "gender": character["gender"],
                    "race": character["race"],
                    "description": character["description"],
                    "level": character["level"],
                    "xp": character["xp"],
                    "gold": character["gold"],
                    "stats": from_json(character["stats_json"], {}),
                    "spells": _annotate_assets(from_json(character["spells_json"], []), turn_id),
                    "skills": from_json(character["skills_json"], []),
                    "traits": from_json(character["traits_json"], []),
                    "inventory": _annotate_assets(from_json(character["inventory_json"], []), turn_id),
                    "pets": _annotate_assets(_entity_list(character, "pet_json", "pets_json"), turn_id),
                    "companions": _annotate_assets(_entity_list(character, "companion_json", "companions_json"), turn_id),
                    "mounts": _annotate_assets(_entity_list(character, "mount_json", "mounts_json"), turn_id),
                    "status": from_json(character["status_json"], {}),
                    "action_text": character["action_text"] or "",
                    "reward_roll": _reward_roll_for_mission(mission, character, turn_id),
                }
            )

        missions.append(
            {
                "mission_id": mission["id"],
                "title": mission["title"],
                "type": mission.get("mission_type") or "standard",
                "type_label": mission_type_label(mission.get("mission_type") or "standard"),
                "subtype": mission.get("mission_subtype"),
                "phase": int(mission.get("phase", 1)),
                "max_phase": int(mission.get("max_phase", 1)),
                "max_participants": int(mission.get("max_participants", mission_max_participants(mission))),
                "party_locked": bool(mission.get("party_locked", 0)),
                "lock_warning": mission.get("lock_warning"),
                "continuation_key": mission.get("continuation_key"),
                "boss_name": mission.get("boss_name"),
                "boss_theme": mission.get("boss_theme"),
                "description": mission["description"],
                "difficulty": mission["difficulty"],
                "death_threshold": DEADLY_TRIAL_DEATH_THRESHOLD if mission_is_deadly_trial(mission) else None,
                "personal_danger_threshold": (
                    deadly_trial_personal_danger_threshold(int(mission["difficulty"]))
                    if mission_is_deadly_trial(mission)
                    else None
                ),
                "resolution": {
                    "mode": "group_total",
                    "logic_multipliers": LOGIC_MULTIPLIERS,
                    "critical_success_threshold": math.ceil(
                        int(mission["difficulty"]) * MISSION_CRITICAL_SUCCESS_MULTIPLIER
                    ),
                },
                "status": mission["status"],
                "threat": from_json(mission["threat_json"], {}),
                "participants": participants,
            }
        )

    craft_rows = conn.execute(
        """
        SELECT
            craft_requests.*,
            characters.name AS character_name,
            characters.level AS character_level,
            characters.race AS character_race,
            players.telegram_id,
            players.username
        FROM craft_requests
        JOIN characters ON characters.id = craft_requests.character_id
        JOIN players ON players.id = characters.player_id
        WHERE craft_requests.turn_id = ?
          AND craft_requests.status = 'pending'
        ORDER BY craft_requests.id
        """,
        (turn_id,),
    ).fetchall()
    craft_requests = [
        {
            "craft_request_id": int(row["id"]),
            "turn_id": int(row["turn_id"]),
            "character_id": int(row["character_id"]),
            "character_name": row["character_name"],
            "character_level": int(row["character_level"]),
            "character_race": row["character_race"],
            "telegram_id": int(row["telegram_id"]),
            "username": row["username"],
            "base": from_json(row["base_json"], {}),
            "material": from_json(row["material_json"], {}),
        }
        for row in craft_rows
    ]

    free_action_rows = conn.execute(
        """
        SELECT
            free_actions.id AS free_action_id,
            free_actions.action_text,
            free_actions.submitted_at,
            characters.*,
            players.telegram_id,
            players.username
        FROM free_actions
        JOIN characters ON characters.id = free_actions.character_id
        JOIN players ON players.id = characters.player_id
        WHERE free_actions.turn_id = ?
        ORDER BY characters.id
        """,
        (turn_id,),
    ).fetchall()
    free_actions: list[dict[str, Any]] = []
    for row in free_action_rows:
        character = row_to_dict(row) or {}
        free_actions.append(
            {
                "free_action_id": int(character["free_action_id"]),
                "turn_id": turn_id,
                "character_id": int(character["id"]),
                "telegram_id": int(character["telegram_id"]),
                "username": character["username"],
                "name": character["name"],
                "gender": character["gender"],
                "race": character["race"],
                "description": character["description"],
                "level": character["level"],
                "xp": character["xp"],
                "gold": character["gold"],
                "stats": from_json(character["stats_json"], {}),
                "spells": _annotate_assets(from_json(character["spells_json"], []), turn_id),
                "skills": from_json(character["skills_json"], []),
                "traits": from_json(character["traits_json"], []),
                "inventory": _annotate_assets(from_json(character["inventory_json"], []), turn_id),
                "pets": _annotate_assets(_entity_list(character, "pet_json", "pets_json"), turn_id),
                "companions": _annotate_assets(_entity_list(character, "companion_json", "companions_json"), turn_id),
                "mounts": _annotate_assets(_entity_list(character, "mount_json", "mounts_json"), turn_id),
                "status": from_json(character["status_json"], {}),
                "action_text": character["action_text"] or "",
                "reward_roll": _reward_roll_for_free_action(character, turn_id, str(character["action_text"] or "")),
                "free_action_resolution": {
                    "mode": "intention_and_tone",
                    "signals": ["intention", "method", "world_connection", "creativity"],
                    "notes": (
                        "Evaluate what the player wants, the tone of the scene, the relevant stat, assets, "
                        "relationships, and how the world can answer. Reward interesting, clear, playable intent."
                    ),
                },
            }
        )

    return {
        "turn_id": turn["id"],
        "turn_title": turn["title"],
        "deadline": turn["deadline"],
        "art": {
            "prompt": turn.get("art_prompt"),
            "telegram_file_id": turn.get("art_file_id"),
            "caption": turn.get("art_caption"),
        },
        "world": {"city": "Танелорн", "guild": "Авентура"},
        "missions": missions,
        "craft_requests": craft_requests,
        "free_actions": free_actions,
    }


def mark_exported(conn: sqlite3.Connection, turn_id: int, export_path: Path) -> None:
    conn.execute("UPDATE turns SET export_path = ? WHERE id = ?", (str(export_path), turn_id))
    conn.commit()


def apply_result_payload(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    turn_id = int(payload["turn_id"])
    turn = get_turn(conn, turn_id)
    if not turn:
        raise ValueError(f"Ход #{turn_id} не найден.")

    for mission_result in payload.get("mission_results", []):
        mission_id = int(mission_result["mission_id"])
        status = mission_result["status"]

        mission = row_to_dict(
            conn.execute("SELECT * FROM missions WHERE id = ? AND turn_id = ?", (mission_id, turn_id)).fetchone()
        )
        if not mission:
            raise ValueError(f"Миссия #{mission_id} не найдена в ходе #{turn_id}.")

        _validate_group_resolution(conn, mission, mission_result)
        _validate_final_boss_rewards(conn, mission, mission_result)
        storage_status = "completed" if status in {"success", "critical_success"} else status
        conn.execute("UPDATE missions SET status = ? WHERE id = ?", (storage_status, mission_id))
        conn.execute(
            """
            INSERT INTO results (turn_id, mission_id, result_json)
            VALUES (?, ?, ?)
            ON CONFLICT(turn_id, mission_id) DO UPDATE SET
                result_json = excluded.result_json,
                created_at = CURRENT_TIMESTAMP,
                published_at = NULL
            """,
            (turn_id, mission_id, to_json(mission_result)),
        )
        _upsert_chronicle_entry(conn, turn, mission, mission_result)

        for player_result in mission_result.get("player_results", []):
            character_id = int(player_result["character_id"])
            _apply_used_asset_cooldowns(conn, turn_id, character_id, player_result)
            for change in player_result.get("changes", []):
                _validate_death_outcome_change_allowed(mission, mission_result, player_result, change)
                _validate_group_level_change_allowed(mission, mission_result, player_result, change)
                _validate_reward_change_allowed(mission, mission_result, player_result, change)
                _apply_character_change(conn, turn_id, character_id, change, mission)

    for craft_result in payload.get("craft_results", []):
        _apply_craft_result(conn, turn_id, craft_result)

    free_action_results = payload.get("free_action_results", [])
    if free_action_results:
        _apply_free_action_result(conn, turn_id, _merge_free_action_results(conn, turn_id, free_action_results))

    conn.execute("UPDATE turns SET status = 'resolved' WHERE id = ?", (turn_id,))
    conn.commit()


def _merge_free_action_results(
    conn: sqlite3.Connection, turn_id: int, free_action_results: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_rows = conn.execute(
        "SELECT character_id FROM free_actions WHERE turn_id = ? ORDER BY character_id",
        (turn_id,),
    ).fetchall()
    expected_ids = {int(row["character_id"]) for row in expected_rows}
    if not expected_ids:
        raise ValueError("В ходе нет свободных ходов для обработки.")

    merged: dict[str, Any] = {"player_results": []}
    summaries: list[str] = []
    overviews: list[str] = []
    world_changes: list[Any] = []
    seen_ids: set[int] = set()

    for free_action_result in free_action_results:
        if not isinstance(free_action_result, dict):
            raise ValueError("free_action_result должен быть объектом.")
        player_results = free_action_result.get("player_results", [])
        if not isinstance(player_results, list):
            raise ValueError("free_action_result.player_results должен быть списком.")
        summary = str(free_action_result.get("public_summary") or "").strip()
        overview = str(free_action_result.get("public_overview") or "").strip()
        if summary:
            summaries.append(summary)
        if overview:
            overviews.append(overview)
        changes = free_action_result.get("world_changes", [])
        if isinstance(changes, list):
            world_changes.extend(changes)
        for player_result in player_results:
            character_id = int(player_result.get("character_id") or 0)
            if character_id in seen_ids:
                raise ValueError("Свободный ход содержит повторный результат одного героя.")
            seen_ids.add(character_id)
            merged["player_results"].append(player_result)

    if expected_ids != seen_ids:
        raise ValueError("Результаты свободного хода должны содержать каждого участника свободного хода ровно один раз.")

    merged["public_summary"] = "\n".join(summaries)
    merged["public_overview"] = "\n\n".join(overviews)
    if world_changes:
        merged["world_changes"] = world_changes
    return merged


def _apply_free_action_result(conn: sqlite3.Connection, turn_id: int, free_action_result: dict[str, Any]) -> None:
    player_results = free_action_result.get("player_results", [])
    if not isinstance(player_results, list):
        raise ValueError("free_action_result.player_results должен быть списком.")
    expected_rows = conn.execute(
        "SELECT character_id FROM free_actions WHERE turn_id = ? ORDER BY character_id",
        (turn_id,),
    ).fetchall()
    expected_ids = {int(row["character_id"]) for row in expected_rows}
    result_ids = {
        int(player_result["character_id"])
        for player_result in player_results
        if player_result.get("character_id") is not None
    }
    if expected_ids != result_ids:
        raise ValueError("Результат свободного хода должен содержать результат каждого участника свободного хода.")

    conn.execute(
        """
        INSERT INTO free_action_results (turn_id, result_json)
        VALUES (?, ?)
        ON CONFLICT(turn_id) DO UPDATE SET
            result_json = excluded.result_json,
            created_at = CURRENT_TIMESTAMP,
            published_at = NULL
        """,
        (turn_id, to_json(free_action_result)),
    )
    for player_result in player_results:
        character_id = int(player_result["character_id"])
        _apply_used_asset_cooldowns(conn, turn_id, character_id, player_result)
        for change in player_result.get("changes", []):
            _validate_free_action_change_allowed(player_result, change)
            _apply_character_change(conn, turn_id, character_id, change, None)


def _apply_craft_result(conn: sqlite3.Connection, turn_id: int, craft_result: dict[str, Any]) -> None:
    request_id = int(craft_result.get("craft_request_id") or craft_result.get("id") or 0)
    if request_id <= 0:
        raise ValueError("craft_result требует craft_request_id.")
    request = row_to_dict(
        conn.execute(
            "SELECT * FROM craft_requests WHERE id = ? AND turn_id = ?",
            (request_id, turn_id),
        ).fetchone()
    )
    if not request:
        raise ValueError(f"Крафт-заявка #{request_id} не найдена в ходе #{turn_id}.")
    if request.get("status") == "completed":
        return

    character_id = int(request["character_id"])
    character = _character_by_id(conn, character_id)
    if not character:
        raise ValueError(f"Персонаж #{character_id} не найден.")
    base = from_json(request["base_json"], {})
    material = from_json(request["material_json"], {})
    relationship = str(craft_result.get("relationship") or "weak").strip().lower()
    result = _normalize_reward_object(craft_result.get("result") or craft_result.get("value"))
    result_type = _normalize_asset_type(result.get("type") or craft_result.get("result_type") or base.get("type"))
    base_type = _normalize_asset_type(base.get("type"))
    if result_type != base_type:
        raise ValueError("Результат крафта должен сохранять тип основы.")
    expected_level = craft_result_level(int(base.get("level", 1)), int(material.get("level", 1)), relationship)
    if int(result["level"]) != expected_level:
        raise ValueError(f"Уровень результата крафта должен быть {expected_level}.")
    result["type"] = result_type
    inherited_cooldown_until = max(
        int(base.get("cooldown_until_turn", 0) or 0),
        int(material.get("cooldown_until_turn", 0) or 0),
    )
    if inherited_cooldown_until > turn_id:
        result["cooldown_until_turn"] = inherited_cooldown_until
    _add_craft_result_asset(conn, character, result_type, result)
    stored_result = {
        "status": "completed",
        "relationship": relationship if relationship in CRAFT_RELATIONSHIP_MULTIPLIERS else "weak",
        "base": base,
        "material": material,
        "result": result,
        "message": str(craft_result.get("message") or "").strip(),
    }
    conn.execute(
        """
        UPDATE craft_requests
        SET status = 'completed',
            result_json = ?,
            completed_at = CURRENT_TIMESTAMP,
            published_at = NULL
        WHERE id = ?
        """,
        (to_json(stored_result), request_id),
    )
    _log_change(conn, turn_id, character_id, "craft_result", {"base": base, "material": material}, result, "Результат крафта")


def _add_craft_result_asset(
    conn: sqlite3.Connection,
    character: dict[str, Any],
    result_type: str,
    result: dict[str, Any],
) -> None:
    reward = dict(result)
    reward.pop("type", None)
    _ensure_unique_asset_name(character, reward["name"])
    if result_type == "inventory":
        inventory = from_json(character["inventory_json"], [])
        reward["uid"] = str(reward.get("uid") or _new_item_uid())
        conn.execute("UPDATE characters SET inventory_json = ? WHERE id = ?", (to_json([*inventory, reward]), character["id"]))
        return
    if result_type == "spells":
        spells = from_json(character["spells_json"], [])
        conn.execute("UPDATE characters SET spells_json = ? WHERE id = ?", (to_json([*spells, reward]), character["id"]))
        return
    if result_type in {"pet", "companion", "mount"}:
        column = _entity_list_column(result_type)
        entities = _character_entities(character, result_type)
        conn.execute(f"UPDATE characters SET {column} = ? WHERE id = ?", (to_json([*entities, reward]), character["id"]))
        return
    raise ValueError("Неизвестный тип результата крафта.")


def _upsert_chronicle_entry(
    conn: sqlite3.Connection,
    turn: dict[str, Any],
    mission: dict[str, Any],
    mission_result: dict[str, Any],
) -> None:
    summary = str(mission_result.get("public_summary") or "").strip()
    if not summary:
        summary = "Итог миссии не записан."
    world_changes = mission_result.get("world_changes", [])
    if not isinstance(world_changes, list):
        world_changes = [str(world_changes)]
    boss_trophy_entry = _boss_trophy_chronicle_entry(conn, mission_result)
    if boss_trophy_entry and boss_trophy_entry not in world_changes:
        world_changes.append(boss_trophy_entry)

    conn.execute(
        """
        INSERT INTO city_chronicle (
            turn_id,
            mission_id,
            turn_title,
            mission_title,
            status,
            public_summary,
            world_changes_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(turn_id, mission_id) DO UPDATE SET
            turn_title = excluded.turn_title,
            mission_title = excluded.mission_title,
            status = excluded.status,
            public_summary = excluded.public_summary,
            world_changes_json = excluded.world_changes_json,
            created_at = CURRENT_TIMESTAMP
        """,
        (
            int(turn["id"]),
            int(mission["id"]),
            turn["title"],
            mission["title"],
            mission_result["status"],
            summary,
            to_json(world_changes),
        ),
    )


def _boss_trophy_chronicle_entry(conn: sqlite3.Connection, mission_result: dict[str, Any]) -> str | None:
    trophy_notes: list[str] = []
    for player_result in mission_result.get("player_results", []):
        character_id = player_result.get("character_id")
        if character_id is None:
            continue
        character = _character_by_id(conn, int(character_id))
        if not character:
            continue
        for change in player_result.get("changes", []):
            if str(change.get("source") or "").strip() != "boss_trophy":
                continue
            trophy_name = _boss_trophy_change_name(change)
            if trophy_name:
                trophy_notes.append(f"{character.get('name', 'Неизвестный герой')} — {trophy_name}")
    if not trophy_notes:
        return None
    return "Победители унесли трофеи босса: " + "; ".join(trophy_notes) + "."


def _boss_trophy_change_name(change: dict[str, Any]) -> str:
    field = str(change.get("field") or "")
    if field == "inventory":
        item = change.get("item") or change.get("value") or {}
        return _leveled_reward_name(item)
    if field == "spells":
        spell = change.get("spell") or change.get("value") or {}
        return _leveled_reward_name(spell)
    if field == "pet":
        pet = change.get("pet") or change.get("value") or {}
        return _leveled_reward_name(pet)
    if field == "companion":
        companion = change.get("companion") or change.get("value") or {}
        return _leveled_reward_name(companion)
    if field == "mount":
        mount = change.get("mount") or change.get("value") or {}
        return _leveled_reward_name(mount)
    return ""


def _leveled_reward_name(value: Any) -> str:
    if isinstance(value, dict):
        return f"{value.get('name', 'без имени')} ур. {value.get('level', 1)}"
    return str(value or "")


def list_city_chronicle(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM city_chronicle
        ORDER BY turn_id DESC, mission_id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    chronicle = [row_to_dict(row) or {} for row in rows]
    chronicle.reverse()
    return chronicle


def build_heroes_snapshot(conn: sqlite3.Connection, turn_id: int | None = None) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT
            characters.*,
            players.telegram_id,
            players.username,
            players.notify_enabled
        FROM characters
        JOIN players ON players.id = characters.player_id
        WHERE characters.is_active = 1
        ORDER BY characters.id
        """
    ).fetchall()

    availability_turn_id = turn_id if turn_id is not None else _cooldown_reference_turn_id(conn)
    heroes: list[dict[str, Any]] = []
    for row in rows:
        character = row_to_dict(row) or {}
        heroes.append(
            {
                "character_id": int(character["id"]),
                "telegram_id": int(character["telegram_id"]),
                "username": character.get("username"),
                "notify_enabled": bool(character.get("notify_enabled", 1)),
                "name": character["name"],
                "gender": character["gender"],
                "race": character["race"],
                "description": character["description"],
                "level": int(character["level"]),
                "xp": int(character["xp"]),
                "gold": int(character["gold"]),
                "stats": from_json(character["stats_json"], DEFAULT_STATS),
                "spells": _annotate_assets(from_json(character["spells_json"], []), availability_turn_id),
                "skills": from_json(character["skills_json"], []),
                "traits": from_json(character["traits_json"], []),
                "inventory": _annotate_assets(from_json(character["inventory_json"], []), availability_turn_id),
                "pets": _annotate_assets(_entity_list(character, "pet_json", "pets_json"), availability_turn_id),
                "companions": _annotate_assets(_entity_list(character, "companion_json", "companions_json"), availability_turn_id),
                "mounts": _annotate_assets(_entity_list(character, "mount_json", "mounts_json"), availability_turn_id),
                "status": from_json(character["status_json"], {}),
                "created_at": character.get("created_at"),
            }
        )

    return {
        "turn_id": turn_id,
        "heroes": heroes,
    }


def _apply_used_asset_cooldowns(
    conn: sqlite3.Connection,
    turn_id: int,
    character_id: int,
    player_result: dict[str, Any],
) -> None:
    check = player_result.get("check") if isinstance(player_result.get("check"), dict) else {}
    used_assets = check.get("used_assets", [])
    if not used_assets:
        return
    if not isinstance(used_assets, list):
        raise ValueError("check.used_assets должен быть списком примененных активов.")
    character = _character_by_id(conn, character_id)
    if not character:
        raise ValueError(f"Персонаж #{character_id} не найден.")
    collections = {
        "inventory": _character_inventory(character),
        "spells": _character_spells(character),
        "pet": _character_entities(character, "pet"),
        "companion": _character_entities(character, "companion"),
        "mount": _character_entities(character, "mount"),
    }
    seen: set[tuple[str, str]] = set()
    for reference in used_assets:
        if not isinstance(reference, dict):
            raise ValueError("Каждый примененный актив в check.used_assets должен быть объектом.")
        asset_type = _normalize_asset_type(reference.get("type") or reference.get("field"))
        name = str(reference.get("name") or "").strip()
        uid = str(reference.get("uid") or "").strip()
        identity = uid if asset_type == "inventory" and uid else name.casefold()
        if not asset_type or not identity:
            raise ValueError("Примененный актив должен содержать type и name либо uid для предмета.")
        if (asset_type, identity) in seen:
            continue
        seen.add((asset_type, identity))
        selected = next(
            (
                asset
                for asset in collections[asset_type]
                if (
                    str(asset.get("uid") or "") == uid
                    if asset_type == "inventory" and uid
                    else str(asset.get("name") or "").strip().casefold() == name.casefold()
                )
            ),
            None,
        )
        if selected is None:
            raise ValueError(f"Примененный актив '{name or uid}' не найден у героя.")
        if not asset_is_active(selected, turn_id):
            raise ValueError(f"Актив '{selected.get('name', name)}' находится на перезарядке и не может дать бонус.")
        duration = max(1, int(selected.get("cooldown_turns", DEFAULT_ASSET_COOLDOWN_TURNS) or DEFAULT_ASSET_COOLDOWN_TURNS))
        selected["cooldown_until_turn"] = int(turn_id) + duration
    conn.execute(
        """
        UPDATE characters
        SET inventory_json = ?, spells_json = ?, pets_json = ?, companions_json = ?, mounts_json = ?
        WHERE id = ?
        """,
        (
            to_json(collections["inventory"]),
            to_json(collections["spells"]),
            to_json(collections["pet"]),
            to_json(collections["companion"]),
            to_json(collections["mount"]),
            character_id,
        ),
    )


def _apply_character_change(
    conn: sqlite3.Connection,
    turn_id: int,
    character_id: int,
    change: dict[str, Any],
    mission: dict[str, Any] | None,
) -> None:
    mission_difficulty = int(mission["difficulty"]) if mission is not None else 1
    allowed_scalar_fields = {"level", "gold"}
    field = change["field"]
    reason = change.get("reason", "")

    character = row_to_dict(conn.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone())
    if not character:
        raise ValueError(f"Персонаж #{character_id} не найден.")

    if field in allowed_scalar_fields:
        old_value = character[field]
        if "delta" in change:
            new_value = int(old_value) + int(change["delta"])
        elif "value" in change:
            new_value = int(change["value"])
        else:
            raise ValueError(f"Изменение поля {field} требует delta или value.")

        if field == "gold":
            if not _is_gm_override(change) and change.get("source") != "consolation_reward":
                # Gold rewards are validated against backend reward_roll separately.
                # Do not apply the generic mission difficulty cap here, because
                # the gold economy may intentionally scale above reward_level_bounds
                # via GOLD_REWARD_MULTIPLIER.
                pass
            elif change.get("source") == "consolation_reward":
                _validate_reward_level(int(new_value) - int(old_value), mission_difficulty, "gold")
        if field in {"level", "gold"}:
            new_value = max(0, new_value)

        conn.execute(f"UPDATE characters SET {field} = ? WHERE id = ?", (new_value, character_id))
        conn.execute(
            """
            INSERT INTO change_log (turn_id, character_id, field, old_value, new_value, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (turn_id, character_id, field, str(old_value), str(new_value), reason),
        )
        return

    if field in {"inventory", "spells"}:
        column = "inventory_json" if field == "inventory" else "spells_json"
        old_value = from_json(character[column], [])
        reward = _normalize_reward_object(change.get("item") or change.get("spell") or change.get("value"))
        if field == "inventory":
            reward["uid"] = str(reward.get("uid") or _new_item_uid())
        _ensure_unique_asset_name(character, reward["name"])
        if mission is not None and not _is_gm_override(change) and change.get("source") != "boss_trophy":
            _validate_reward_level_for_mission(int(reward["level"]), mission, field)
        new_value = [*old_value, reward]
        conn.execute(f"UPDATE characters SET {column} = ? WHERE id = ?", (to_json(new_value), character_id))
        _log_change(conn, turn_id, character_id, field, old_value, new_value, reason)
        return

    if field == "stat":
        stat_name = str(change.get("stat") or change.get("name") or "").strip().lower()
        if stat_name not in STAT_NAMES:
            raise ValueError(f"Неизвестная характеристика для награды: {stat_name}.")
        old_stats = from_json(character["stats_json"], DEFAULT_STATS)
        old_value = int(old_stats.get(stat_name, 0))
        if "delta" in change:
            new_value = old_value + int(change["delta"])
        elif "value" in change:
            new_value = int(change["value"])
        else:
            raise ValueError("Изменение характеристики требует stat и delta или value.")
        if new_value < 1:
            raise ValueError("Характеристика не может быть меньше 1.")
        new_stats = dict(old_stats)
        new_stats[stat_name] = new_value
        conn.execute("UPDATE characters SET stats_json = ? WHERE id = ?", (to_json(new_stats), character_id))
        _log_change(conn, turn_id, character_id, "stat", old_stats, new_stats, reason)
        return

    if field == "status":
        old_value = from_json(character["status_json"], {})
        new_value = _apply_status_change(old_value, change)
        conn.execute("UPDATE characters SET status_json = ? WHERE id = ?", (to_json(new_value), character_id))
        _log_change(conn, turn_id, character_id, "status", old_value, new_value, reason)
        return

    if field == "death_outcome":
        _apply_death_outcome_change(conn, turn_id, character, change, reason)
        return

    if field in {"pet", "familiar", "mount", "companion"}:
        normalized_field = "pet" if field == "familiar" else field
        column = _entity_list_column(normalized_field)
        old_value = _entity_list(character, f"{normalized_field}_json", column)
        new_value = _normalize_reward_object(change.get(field) or change.get(normalized_field) or change.get("value"))
        _ensure_unique_asset_name(character, new_value["name"])
        if mission is not None and not _is_gm_override(change) and change.get("source") != "boss_trophy":
            _validate_reward_level_for_mission(int(new_value["level"]), mission, normalized_field)
        updated_value = [*old_value, new_value]
        conn.execute(f"UPDATE characters SET {column} = ? WHERE id = ?", (to_json(updated_value), character_id))
        _log_change(conn, turn_id, character_id, normalized_field, old_value, updated_value, reason)
        return

    raise ValueError(f"Поле {field} пока нельзя менять через импорт результата.")


def _apply_death_outcome_change(
    conn: sqlite3.Connection,
    turn_id: int,
    character: dict[str, Any],
    change: dict[str, Any],
    reason: str,
) -> None:
    outcome = str(change.get("outcome") or "").strip().lower()
    character_id = int(character["id"])
    if outcome == "ghost":
        transformed = ghost_character_state(character)
        old_value = {"race": character["race"], "stats": from_json(character["stats_json"], DEFAULT_STATS)}
        new_value = {"race": transformed["race"], "stats": transformed["stats"]}
        conn.execute(
            "UPDATE characters SET race = ?, stats_json = ? WHERE id = ?",
            (transformed["race"], to_json(transformed["stats"]), character_id),
        )
        _log_change(conn, turn_id, character_id, "death_outcome", old_value, new_value, reason or "Посмертный исход: призрак")
        return
    if outcome == "skeleton":
        transformed = skeleton_character_state(character)
        old_value = {"race": character["race"], "stats": from_json(character["stats_json"], DEFAULT_STATS)}
        new_value = {"race": transformed["race"], "stats": transformed["stats"]}
        conn.execute(
            "UPDATE characters SET race = ?, stats_json = ? WHERE id = ?",
            (transformed["race"], to_json(transformed["stats"]), character_id),
        )
        _log_change(conn, turn_id, character_id, "death_outcome", old_value, new_value, reason or "Посмертный исход: скелет")
        return
    if outcome == "reincarnation":
        payload = change.get("reincarnation") if isinstance(change.get("reincarnation"), dict) else reincarnation_payload(character)
        old_status = from_json(character["status_json"], {})
        old_active = old_status.get("active", []) if isinstance(old_status, dict) else []
        if not isinstance(old_active, list):
            old_active = []
        new_status = {
            **(old_status if isinstance(old_status, dict) else {}),
            "active": [
                *old_active,
                {
                    "name": "Ожидает реинкарнации",
                    "note": (
                        f"stat_pool={payload.get('stat_pool')}; old_name_locked={payload.get('locked_name')}; "
                        f"legacy={payload.get('legacy') or 'нет'}"
                    ),
                },
            ],
            "reincarnation": payload,
        }
        conn.execute(
            "UPDATE characters SET status_json = ?, is_active = 0 WHERE id = ?",
            (to_json(new_status), character_id),
        )
        _log_change(conn, turn_id, character_id, "death_outcome", old_status, new_status, reason or "Посмертный исход: реинкарнация")
        return
    raise ValueError("death_outcome должен быть ghost, skeleton или reincarnation.")


def _apply_status_change(old_value: Any, change: dict[str, Any]) -> dict[str, Any]:
    statuses = old_value if isinstance(old_value, dict) else {}
    active = statuses.get("active", [])
    if not isinstance(active, list):
        active = []

    action = str(change.get("action") or "add").strip().lower()
    value = change.get("status") or change.get("value") or change.get("name")
    if isinstance(value, str):
        status = {"name": value.strip()}
    elif isinstance(value, dict):
        status = dict(value)
        status["name"] = str(status.get("name", "")).strip()
    else:
        raise ValueError("Изменение состояния требует status, value или name.")
    if not status.get("name"):
        raise ValueError("У состояния должно быть имя.")

    key = str(status["name"]).casefold()
    if action == "remove":
        new_active = [
            item for item in active
            if str(item.get("name") if isinstance(item, dict) else item).casefold() != key
        ]
    elif action == "set":
        new_active = [status]
    elif action == "add":
        new_active = [
            item for item in active
            if str(item.get("name") if isinstance(item, dict) else item).casefold() != key
        ]
        new_active.append(status)
    else:
        raise ValueError("action для состояния должен быть add, remove или set.")

    return {**statuses, "active": new_active}


def _is_completed_final_phased_boss(mission: dict[str, Any], mission_result: dict[str, Any]) -> bool:
    return (
        mission_is_phased_boss(mission)
        and int(mission.get("phase", 1)) >= int(mission.get("max_phase", 1))
        and mission_result.get("status") == "completed"
    )


def _uses_group_resolution(mission_result: dict[str, Any]) -> bool:
    if mission_result.get("status") in {"success", "critical_success"}:
        return True
    return any(
        isinstance(player_result.get("check"), dict)
        and (
            "logic_signals" in player_result["check"]
            or "logic_tier" in player_result["check"]
            or "personal_contribution" in player_result["check"]
        )
        for player_result in mission_result.get("player_results", [])
    )


def _validate_group_resolution(
    conn: sqlite3.Connection,
    mission: dict[str, Any],
    mission_result: dict[str, Any],
) -> None:
    if not _uses_group_resolution(mission_result):
        return
    expected_ids = _mission_action_character_ids(conn, int(mission["id"]), int(mission["turn_id"]))
    result_ids = {
        int(player_result["character_id"])
        for player_result in mission_result.get("player_results", [])
        if player_result.get("character_id") is not None
    }
    if expected_ids != result_ids:
        raise ValueError("Групповой результат должен содержать результат каждого участника миссии.")
    transferred_keys: list[tuple[str, str, int]] = []
    received_keys: list[tuple[str, str, int]] = []
    for player_result in mission_result.get("player_results", []):
        check = player_result.get("check") if isinstance(player_result.get("check"), dict) else {}
        used_assets = check.get("used_assets", [])
        transferred_assets = check.get("transferred_assets", [])
        received_assets = check.get("received_assets", [])
        if not all(isinstance(value, list) for value in (used_assets, transferred_assets, received_assets)):
            raise ValueError("check.used_assets, transferred_assets и received_assets должны быть списками.")
        used_keys = [_mechanical_asset_key(asset) for asset in used_assets]
        for asset in transferred_assets:
            key = _mechanical_asset_key(asset)
            if key not in used_keys:
                raise ValueError("Переданный союзнику актив должен также присутствовать в used_assets владельца.")
            transferred_keys.append(key)
        received_keys.extend(_mechanical_asset_key(asset) for asset in received_assets)
    if sorted(transferred_keys) != sorted(received_keys):
        raise ValueError("Переданные и полученные союзниками активы должны совпадать.")

    entries: list[dict[str, int]] = []
    for player_result in mission_result.get("player_results", []):
        check = player_result.get("check") if isinstance(player_result.get("check"), dict) else {}
        signals = check.get("logic_signals")
        if not isinstance(signals, dict):
            raise ValueError("Новый групповой расчет требует check.logic_signals с goal/method/scene.")
        tier = logic_tier_from_signals(signals)
        if int(check.get("logic_tier", -1)) != tier:
            raise ValueError("check.logic_tier не соответствует сигналам goal/method/scene.")
        character = _character_by_id(conn, int(player_result["character_id"]))
        if not character:
            raise ValueError(f"Персонаж #{player_result['character_id']} не найден.")
        stat_name = str(check.get("stat") or "").strip().lower()
        if stat_name not in STAT_NAMES:
            raise ValueError("Новый групповой расчет требует check.stat с выбранной характеристикой героя.")
        core_score = hero_core_score(character, stat_name)
        if int(check.get("core_score", -1)) != core_score:
            raise ValueError("check.core_score должен соответствовать уровню героя и выбранной характеристике.")
        transferred_assets = check.get("transferred_assets", [])
        scoring_assets = list(check.get("used_assets", []))
        for transferred in transferred_assets:
            key = _mechanical_asset_key(transferred)
            scoring_assets.remove(next(asset for asset in scoring_assets if _mechanical_asset_key(asset) == key))
        scoring_assets.extend(check.get("received_assets", []))
        expected_base_score = calculate_hero_score(character, stat_name, scoring_assets)
        base_score = int(check.get("base_score", check.get("hero_score", 0)))
        if base_score != expected_base_score:
            raise ValueError("check.base_score не соответствует ядру героя и примененным активам с убывающей отдачей.")
        contribution = personal_contribution(base_score, tier, core_score)
        if int(check.get("personal_contribution", -1)) != contribution:
            raise ValueError("check.personal_contribution не соответствует base_score и logic_tier.")
        if check.get("success") is not (tier >= 2):
            raise ValueError("check.success должен быть true только для полноценного или сильного вклада.")
        entries.append({"logic_tier": tier, "personal_contribution": contribution})

    applied_teamwork_bonus = 0
    teamwork_bonus = mission_result.get("teamwork_bonus")
    if teamwork_bonus is not None:
        if not isinstance(teamwork_bonus, dict):
            raise ValueError("teamwork_bonus должен быть объектом с value и reason.")
        applied_teamwork_bonus = int(teamwork_bonus.get("value", 0))
        expected_teamwork_bonus = mission_teamwork_bonus(entries)
        if applied_teamwork_bonus != expected_teamwork_bonus:
            raise ValueError(f"teamwork_bonus должен быть {expected_teamwork_bonus} для текущих вкладов.")
        if applied_teamwork_bonus and not str(teamwork_bonus.get("reason") or "").strip():
            raise ValueError("teamwork_bonus требует reason.")

    mission_total = sum(entry["personal_contribution"] for entry in entries) + applied_teamwork_bonus
    for player_result in mission_result.get("player_results", []):
        check = player_result.get("check", {})
        if int(check.get("mission_total", -1)) != mission_total:
            raise ValueError("У каждого участника check.mission_total должен совпадать с общей суммой вклада.")

    if mission_is_phased_boss(mission):
        passed = mission_total >= int(mission["difficulty"])
        final_phase = int(mission.get("phase", 1)) >= int(mission.get("max_phase", 1))
        expected_status = "completed" if passed and final_phase else "ongoing" if passed else "failed"
    else:
        expected_status = group_mission_status(int(mission["difficulty"]), entries, applied_teamwork_bonus)
    if mission_result.get("status") != expected_status:
        raise ValueError(
            f"Статус миссии по суммарному вкладу должен быть {expected_status}, "
            f"сейчас {mission_result.get('status')}."
        )


def _mechanical_asset_key(asset: Any) -> tuple[str, str, int]:
    if not isinstance(asset, dict):
        raise ValueError("Ссылка на примененный актив должна быть объектом.")
    asset_type = _normalize_asset_type(asset.get("type") or asset.get("field"))
    name = str(asset.get("name") or "").strip()
    uid = str(asset.get("uid") or "").strip()
    identity = uid if asset_type == "inventory" and uid else name.casefold()
    if not asset_type or not identity:
        raise ValueError("Ссылка на примененный актив должна содержать type и name либо uid для предмета.")
    return asset_type, identity, int(asset.get("level", 0))


def _is_successful_result(mission_result: dict[str, Any]) -> bool:
    return mission_result.get("status") in {"completed", "success", "critical_success"}


def _validate_group_level_change_allowed(
    mission: dict[str, Any],
    mission_result: dict[str, Any],
    player_result: dict[str, Any],
    change: dict[str, Any],
) -> None:
    if change.get("field") != "level" or not _uses_group_resolution(mission_result):
        return
    if _is_completed_final_phased_boss(mission, mission_result):
        return
    tier = int(player_result.get("check", {}).get("logic_tier", 0))
    phase_passed = _is_successful_result(mission_result) or (
        mission_is_phased_boss(mission) and mission_result.get("status") == "ongoing"
    )
    expected_delta = 2 if phase_passed and tier >= 2 else 1 if tier >= 1 else 0
    if int(change.get("delta", 0)) != expected_delta:
        raise ValueError(f"Изменение уровня для вклада logic_tier={tier} должно быть {expected_delta}.")


def _validate_final_boss_rewards(
    conn: sqlite3.Connection,
    mission: dict[str, Any],
    mission_result: dict[str, Any],
) -> None:
    if not _is_completed_final_phased_boss(mission, mission_result):
        return
    expected_ids = _mission_action_character_ids(conn, int(mission["id"]), int(mission["turn_id"]))
    player_results = mission_result.get("player_results", [])
    result_by_id = {
        int(player_result["character_id"]): player_result
        for player_result in player_results
        if player_result.get("character_id") is not None
    }
    missing_ids = expected_ids - set(result_by_id)
    if missing_ids:
        raise ValueError("Финальная победа над боссом должна содержать результат для каждого участника.")
    for character_id in expected_ids:
        player_result = result_by_id[character_id]
        changes = player_result.get("changes", [])
        trophy_changes = [change for change in changes if change.get("source") == "boss_trophy"]
        ordinary_rewards = [
            change for change in changes
            if change.get("field") in {"inventory", "spells", "stat", "pet", "familiar", "companion", "mount", "gold"}
            and change.get("source") != "boss_trophy"
        ]
        if len(trophy_changes) != 1:
            raise ValueError("Каждый участник победной финальной фазы босса должен получить один boss_trophy.")
        if len(ordinary_rewards) != 1:
            raise ValueError("Каждый участник победной финальной фазы босса должен получить одну обычную награду.")
        if ordinary_rewards[0].get("field") == "gold":
            raise ValueError("Дублоны не могут быть наградой за победную финальную фазу босса.")
        if not player_result.get("reward_roll"):
            raise ValueError("Для обычной награды финального босса нужен backend reward_roll.")


def _validate_reward_change_allowed(
    mission: dict[str, Any],
    mission_result: dict[str, Any],
    player_result: dict[str, Any],
    change: dict[str, Any],
) -> None:
    reward_fields = {"gold", "inventory", "spells", "stat", "pet", "familiar", "companion", "mount"}
    if change.get("field") not in reward_fields:
        return
    _validate_titled_reward_exclusivity(mission, change)
    if _is_gm_override(change):
        return
    if change.get("source") == "boss_trophy":
        _validate_boss_trophy_change(mission, mission_result, player_result, change)
        return
    if not _is_successful_result(mission_result):
        raise ValueError("Награды можно выдавать только за успешно завершенные миссии.")
    if _is_completed_final_phased_boss(mission, mission_result):
        if change.get("field") == "gold":
            raise ValueError("Дублоны не могут быть наградой за победную финальную фазу босса.")
        if not player_result.get("reward_roll"):
            raise ValueError("Награда должна использовать backend reward_roll из экспорта хода.")
        _validate_change_matches_reward_roll(player_result, change, mission_result)
        return
    if player_result.get("check", {}).get("success") is not True:
        if _uses_group_resolution(mission_result):
            raise ValueError("При слабом вкладе в групповой миссии предметная награда не выдается.")
        if change.get("field") != "gold":
            raise ValueError("При личном провале в completed миссии можно выдать только утешительное золото.")
        _validate_consolation_gold_change(player_result, change)
        return
    if not player_result.get("reward_roll"):
        raise ValueError("Награда должна использовать backend reward_roll из экспорта хода.")
    _validate_change_matches_reward_roll(player_result, change, mission_result)


def _validate_free_action_change_allowed(player_result: dict[str, Any], change: dict[str, Any]) -> None:
    reward_fields = {"gold", "inventory", "spells", "stat", "pet", "familiar", "companion", "mount"}
    if change.get("field") not in reward_fields or _is_gm_override(change):
        return
    if not player_result.get("reward_roll"):
        raise ValueError("Награда свободного хода должна использовать backend reward_roll из экспорта хода.")
    _validate_change_matches_reward_roll(player_result, change, None)


def _validate_death_outcome_change_allowed(
    mission: dict[str, Any],
    mission_result: dict[str, Any],
    player_result: dict[str, Any],
    change: dict[str, Any],
) -> None:
    if change.get("field") != "death_outcome":
        return
    if not mission_is_deadly_trial(mission):
        raise ValueError("Посмертный исход допустим только в deadly_trial.")
    check = player_result.get("check") if isinstance(player_result.get("check"), dict) else {}
    if check.get("success") is not False:
        raise ValueError("Посмертный исход допустим только при личном провале.")
    if _uses_group_resolution(mission_result):
        if mission_result.get("status") != "failed":
            raise ValueError("В групповой deadly_trial посмертный исход возможен только при провале миссии.")
        if int(check.get("logic_tier", 0)) > 1:
            raise ValueError("Посмертный исход требует нулевой или слабый личный вклад.")
        margin = deadly_trial_personal_danger_threshold(int(mission["difficulty"])) - int(
            check.get("personal_contribution", 0)
        )
        if margin < DEADLY_TRIAL_DEATH_THRESHOLD:
            raise ValueError(
                f"Посмертный исход требует отставание от личного порога не меньше {DEADLY_TRIAL_DEATH_THRESHOLD}; сейчас {margin}."
            )
    elif "hero_score" in check:
        margin = int(mission["difficulty"]) - int(check.get("hero_score", 0))
        if margin < DEADLY_TRIAL_DEATH_THRESHOLD:
            raise ValueError(
                f"Посмертный исход требует отставание не меньше {DEADLY_TRIAL_DEATH_THRESHOLD}; сейчас {margin}."
            )


def _validate_titled_reward_exclusivity(mission: dict[str, Any], change: dict[str, Any]) -> None:
    reward_value = _reward_payload_from_change(change)
    if not isinstance(reward_value, dict):
        return
    is_titled = str(reward_value.get("rank") or "").strip().lower() == "titled" or reward_value.get("exclusive") == MISSION_TYPE_DEADLY_TRIAL
    if not is_titled:
        return
    field = "pet" if change.get("field") == "familiar" else str(change.get("field") or "")
    if not mission_is_deadly_trial(mission):
        raise ValueError("Титулованные награды доступны только в deadly_trial.")
    if field not in {"pet", "companion", "mount"}:
        raise ValueError("Титулованная deadly_trial награда может быть только питомцем/фамильяром, спутником или маунтом.")
    if reward_value.get("exclusive") != MISSION_TYPE_DEADLY_TRIAL:
        raise ValueError("У титулованной награды должен быть exclusive = deadly_trial.")


def _reward_payload_from_change(change: dict[str, Any]) -> Any:
    field = "pet" if change.get("field") == "familiar" else change.get("field")
    if field == "inventory":
        return change.get("item") or change.get("value")
    if field == "spells":
        return change.get("spell") or change.get("value")
    if field in {"pet", "companion", "mount"}:
        return change.get(field) or change.get(change.get("field")) or change.get("value")
    return change.get("value")


def _is_gm_override(change: dict[str, Any]) -> bool:
    return change.get("gm_override") is True or change.get("source") == "gm_override"


def _validate_change_matches_reward_roll(
    player_result: dict[str, Any],
    change: dict[str, Any],
    mission_result: dict[str, Any] | None = None,
) -> None:
    reward_roll = player_result.get("reward_roll")
    if not reward_roll:
        return

    expected_type = reward_roll.get("type")
    field = "pet" if change.get("field") == "familiar" else change.get("field")
    allowed_types = reward_roll.get("allowed_types")
    if isinstance(allowed_types, list):
        allowed = {"pet" if str(item) == "familiar" else str(item) for item in allowed_types}
    elif expected_type:
        allowed = {"pet" if str(expected_type) == "familiar" else str(expected_type)}
    else:
        allowed = set(COMMON_REWARD_TYPES)
    if field not in allowed:
        if _is_critical_rare_upgrade_allowed(player_result, change, mission_result, field):
            upgrade_allowed_types = reward_roll.get("critical_success_rare_upgrade_allowed_types") or RARE_REWARD_TYPES
            allowed = {"pet" if str(item) == "familiar" else str(item) for item in upgrade_allowed_types}
        else:
            raise ValueError(
                "Награда должна соответствовать backend reward_roll.allowed_types: "
                f"{', '.join(sorted(allowed))}."
            )

    expected_level = int(reward_roll.get("level", 0))
    enhance_reward = (
        isinstance(mission_result, dict)
        and mission_result.get("status") == "critical_success"
        and int(player_result.get("check", {}).get("logic_tier", 0)) >= 3
    )
    if enhance_reward and field != "stat":
        expected_level = math.ceil(expected_level * MISSION_CRITICAL_SUCCESS_MULTIPLIER)
    if field == "gold":
        actual_level = int(change.get("delta", 0))
        expected_gold = expected_level * GOLD_REWARD_MULTIPLIER
        if actual_level != expected_gold:
            raise ValueError(
                f"Золотая награда должна быть равна reward_roll.level * {GOLD_REWARD_MULTIPLIER}: {expected_gold}."
            )
        return
    elif field == "stat":
        stat_name = str(change.get("stat") or change.get("name") or "").strip().lower()
        if stat_name not in STAT_NAMES:
            raise ValueError(f"Награда stat должна указывать одну характеристику: {', '.join(STAT_NAMES)}.")
        actual_level = int(change.get("delta", 0))
        expected_stat_delta = int(reward_roll.get("stat_delta", 1))
        if actual_level != expected_stat_delta:
            raise ValueError(f"Награда stat должна давать delta {expected_stat_delta}.")
        return
    elif field == "inventory":
        actual_level = _reward_level_from_change_value(change.get("item") or change.get("value"))
    elif field == "spells":
        actual_level = _reward_level_from_change_value(change.get("spell") or change.get("value"))
    else:
        actual_level = _reward_level_from_change_value(change.get(change.get("field")) or change.get(field) or change.get("value"))

    if actual_level != expected_level:
        raise ValueError(f"Уровень награды должен соответствовать backend reward_roll: {expected_level}.")


def _is_critical_rare_upgrade_allowed(
    player_result: dict[str, Any],
    change: dict[str, Any],
    mission_result: dict[str, Any] | None,
    field: str,
) -> bool:
    if not isinstance(mission_result, dict):
        return False
    if mission_result.get("status") != "critical_success":
        return False
    if change.get("source") != "critical_rare_upgrade":
        return False
    if int(player_result.get("check", {}).get("logic_tier", 0)) < 3:
        return False
    reward_roll = player_result.get("reward_roll") if isinstance(player_result.get("reward_roll"), dict) else {}
    upgrade_allowed_types = reward_roll.get("critical_success_rare_upgrade_allowed_types") or RARE_REWARD_TYPES
    allowed = {"pet" if str(item) == "familiar" else str(item) for item in upgrade_allowed_types}
    return field in allowed


def _validate_boss_trophy_change(
    mission: dict[str, Any],
    mission_result: dict[str, Any],
    player_result: dict[str, Any],
    change: dict[str, Any],
) -> None:
    if mission_result.get("status") != "completed":
        raise ValueError("Boss trophy можно выдавать только за completed boss-миссию.")
    if not mission_is_phased_boss(mission):
        raise ValueError("Boss trophy допустим только для phased boss-миссии.")
    if int(mission.get("phase", 1)) < int(mission.get("max_phase", 1)):
        raise ValueError("Boss trophy можно выдавать только за последнюю фазу босса.")

    field = "pet" if change.get("field") == "familiar" else change.get("field")
    if field not in {"inventory", "spells", "pet", "companion", "mount"}:
        raise ValueError("Boss trophy должен быть предметом, заклинанием, питомцем, спутником или маунтом.")

    if field == "inventory":
        actual_level = _reward_level_from_change_value(change.get("item") or change.get("value"))
    elif field == "spells":
        actual_level = _reward_level_from_change_value(change.get("spell") or change.get("value"))
    else:
        actual_level = _reward_level_from_change_value(change.get(field) or change.get("value"))

    boss_difficulty = int(mission.get("difficulty", 0))
    min_level, max_level = boss_trophy_level_bounds(boss_difficulty)
    if actual_level < min_level or actual_level > max_level:
        raise ValueError(
            f"Boss trophy должен иметь уровень от {min_level} до {max_level} для босса сложности {boss_difficulty}."
        )


def _reward_level_from_change_value(value: Any) -> int:
    if isinstance(value, dict):
        return int(value.get("level", 0))
    return 0


def _validate_consolation_gold_change(player_result: dict[str, Any], change: dict[str, Any]) -> None:
    reward_roll = player_result.get("reward_roll")
    if not reward_roll:
        raise ValueError("Для утешительного золота нужен backend reward_roll из экспорта хода.")
    if "delta" not in change:
        raise ValueError("Утешительное золото должно задаваться через gold delta.")
    delta = int(change.get("delta", 0))
    expected_max = max(1, int(reward_roll.get("level", 0)) // 2)
    if delta < 1 or delta > expected_max:
        raise ValueError(
            f"Утешительное золото должно быть от 1 до {expected_max} для reward_roll уровня {reward_roll.get('level', 0)}."
        )


def _normalize_reward_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"name": value}
    if not isinstance(value, dict):
        raise ValueError("Награда должна быть объектом или строкой.")

    name = str(value.get("name", "")).strip()
    if not name:
        raise ValueError("У награды должно быть имя.")

    normalized = dict(value)
    normalized["name"] = name
    normalized["level"] = int(normalized.get("level", 1))
    if normalized["level"] < 1:
        raise ValueError("Уровень награды должен быть не меньше 1.")
    return normalized


def _entity_list(character: dict[str, Any], legacy_column: str, list_column: str) -> list[dict[str, Any]]:
    entities = from_json(character.get(list_column), [])
    if entities:
        return entities
    legacy = from_json(character.get(legacy_column), None)
    return [] if legacy is None else [legacy]


def _entity_list_column(field: str) -> str:
    if field == "pet":
        return "pets_json"
    if field == "companion":
        return "companions_json"
    if field == "mount":
        return "mounts_json"
    raise ValueError(f"Неизвестный тип сущности: {field}.")


def _validate_unique_names(names: list[str]) -> None:
    normalized: set[str] = set()
    for name in names:
        key = name.strip().casefold()
        if not key:
            continue
        if key in normalized:
            raise ValueError(f"Имя '{name}' уже используется у персонажа.")
        normalized.add(key)


def _ensure_unique_asset_name(character: dict[str, Any], new_name: str) -> None:
    existing_names: list[str] = []
    for column in ("inventory_json", "spells_json"):
        existing_names.extend(item.get("name", "") for item in from_json(character[column], []))
    for legacy_column, list_column in (
        ("pet_json", "pets_json"),
        ("companion_json", "companions_json"),
        ("mount_json", "mounts_json"),
    ):
        existing_names.extend(entity.get("name", "") for entity in _entity_list(character, legacy_column, list_column))
    _validate_unique_names([*existing_names, new_name])


def _validate_character_name_available(conn: sqlite3.Connection, telegram_id: int, name: str) -> None:
    row = conn.execute(
        """
        SELECT characters.id, players.telegram_id
        FROM characters
        JOIN players ON players.id = characters.player_id
        WHERE lower(characters.name) = lower(?)
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    if row and int(row["telegram_id"]) != telegram_id:
        raise ValueError(f"Герой с именем '{name}' уже существует. Выбери другое имя.")


def _validate_text_length(value: str, label: str, min_length: int, max_length: int) -> None:
    size = len(value.strip())
    if size < min_length:
        raise ValueError(f"{label}: минимум {min_length} символов.")
    if size > max_length:
        raise ValueError(f"{label}: максимум {max_length} символов.")


def _normalize_restore_named_assets(assets: list[Any], asset_label: str, with_uid: bool) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_asset in assets:
        if not isinstance(raw_asset, dict):
            raise ValueError(f"Каждый {asset_label} в restore-файле должен быть объектом.")
        name = str(raw_asset.get("name", "")).strip()
        if not name:
            raise ValueError(f"У {asset_label} в restore-файле должно быть имя.")
        _validate_text_length(name, f"Название {asset_label}", 1, ASSET_NAME_MAX_LENGTH)
        level = int(raw_asset.get("level", 1))
        if level < 1:
            raise ValueError(f"У {asset_label} '{name}' уровень должен быть не меньше 1.")
        item = {"name": name, "level": level}
        _copy_restore_cooldown_fields(raw_asset, item)
        if with_uid:
            item["uid"] = str(raw_asset.get("uid") or _new_item_uid()).strip() or _new_item_uid()
        normalized.append(item)
    return normalized


def _normalize_restore_entities(entities: list[Any], entity_label: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_entity in entities:
        if not isinstance(raw_entity, dict):
            raise ValueError(f"Каждый {entity_label} в restore-файле должен быть объектом.")
        name = str(raw_entity.get("name", "")).strip()
        if not name:
            raise ValueError(f"У сущности типа {entity_label} в restore-файле должно быть имя.")
        _validate_text_length(name, f"Название {entity_label}", 1, ASSET_NAME_MAX_LENGTH)
        level = int(raw_entity.get("level", 1))
        if level < 1:
            raise ValueError(f"У {entity_label} '{name}' уровень должен быть не меньше 1.")
        item = {"name": name, "level": level}
        _copy_restore_cooldown_fields(raw_entity, item)
        normalized.append(item)
    return normalized


def _copy_restore_cooldown_fields(source: dict[str, Any], target: dict[str, Any]) -> None:
    cooldown_turns = int(source.get("cooldown_turns", 0) or 0)
    cooldown_until_turn = int(source.get("cooldown_until_turn", 0) or 0)
    if cooldown_turns > 0:
        target["cooldown_turns"] = cooldown_turns
    if cooldown_until_turn > 0:
        target["cooldown_until_turn"] = cooldown_until_turn


def _normalize_restore_status(status_value: Any) -> dict[str, Any]:
    if isinstance(status_value, dict):
        active = status_value.get("active", [])
        if not isinstance(active, list):
            active = []
        normalized_active: list[dict[str, Any]] = []
        for raw_status in active:
            if isinstance(raw_status, str) and raw_status.strip():
                normalized_active.append({"name": raw_status.strip()})
            elif isinstance(raw_status, dict):
                name = str(raw_status.get("name", "")).strip()
                if name:
                    item = dict(raw_status)
                    item["name"] = name
                    normalized_active.append(item)
        return {**status_value, "active": normalized_active}
    if isinstance(status_value, list):
        active: list[dict[str, Any]] = []
        for raw_status in status_value:
            if isinstance(raw_status, str) and raw_status.strip():
                active.append({"name": raw_status.strip()})
            elif isinstance(raw_status, dict):
                name = str(raw_status.get("name", "")).strip()
                if name:
                    item = dict(raw_status)
                    item["name"] = name
                    active.append(item)
        return {"active": active}
    return {}


def _validate_reward_level(level: int, mission_difficulty: int, field: str) -> None:
    min_level, max_level = reward_level_bounds(mission_difficulty)
    if level < min_level or level > max_level:
        raise ValueError(
            f"Награда {field} должна быть уровня/количества от {min_level} до {max_level} "
            f"для сложности миссии {mission_difficulty}."
        )


def _validate_reward_level_for_mission(level: int, mission: dict[str, Any], field: str) -> None:
    mission_difficulty = int(mission["difficulty"])
    if mission_is_phased_boss(mission) and int(mission.get("phase", 1)) >= int(mission.get("max_phase", 1)):
        min_level, max_level = boss_final_reward_level_bounds(mission_difficulty)
    else:
        min_level, max_level = reward_level_bounds(personal_difficulty_share(mission_difficulty))
        _legacy_min, legacy_max_level = reward_level_bounds(mission_difficulty)
    if mission_is_deadly_trial(mission):
        min_level = deadly_trial_reward_level(min_level, mission_difficulty)
        max_level = deadly_trial_reward_level(max_level, mission_difficulty)
        legacy_max_level = deadly_trial_reward_level(legacy_max_level, mission_difficulty)
    if not (mission_is_phased_boss(mission) and int(mission.get("phase", 1)) >= int(mission.get("max_phase", 1))):
        # Existing open turns may still contain reward_roll values created before group scaling.
        max_level = max(
            math.ceil(max_level * MISSION_CRITICAL_SUCCESS_MULTIPLIER),
            legacy_max_level,
        )
    if level < min_level or level > max_level:
        raise ValueError(
            f"Награда {field} должна быть уровня/количества от {min_level} до {max_level} "
            f"для сложности миссии {mission_difficulty}."
        )


def _log_change(
    conn: sqlite3.Connection,
    turn_id: int,
    character_id: int,
    field: str,
    old_value: Any,
    new_value: Any,
    reason: str,
) -> None:
    conn.execute(
        """
        INSERT INTO change_log (turn_id, character_id, field, old_value, new_value, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (turn_id, character_id, field, to_json(old_value), to_json(new_value), reason),
    )


def pending_publications(conn: sqlite3.Connection, turn_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT results.*, missions.title AS mission_title
        FROM results
        JOIN missions ON missions.id = results.mission_id
        WHERE results.turn_id = ? AND results.published_at IS NULL
        ORDER BY results.mission_id
        """,
        (turn_id,),
    ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def pending_free_action_publications(conn: sqlite3.Connection, turn_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM free_action_results
        WHERE turn_id = ? AND published_at IS NULL
        ORDER BY id
        """,
        (turn_id,),
    ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


def mark_result_published(conn: sqlite3.Connection, result_id: int) -> None:
    conn.execute("UPDATE results SET published_at = CURRENT_TIMESTAMP WHERE id = ?", (result_id,))
    conn.commit()


def mark_free_action_result_published(conn: sqlite3.Connection, result_id: int) -> None:
    conn.execute("UPDATE free_action_results SET published_at = CURRENT_TIMESTAMP WHERE id = ?", (result_id,))
    conn.commit()


def character_telegram_id(conn: sqlite3.Connection, character_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT players.telegram_id
        FROM characters
        JOIN players ON players.id = characters.player_id
        WHERE characters.id = ?
          AND players.notify_enabled = 1
        """,
        (character_id,),
    ).fetchone()
    return None if row is None else int(row["telegram_id"])
