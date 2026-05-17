from __future__ import annotations

import random
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from aventura_bot.db import from_json, row_to_dict, to_json

STAT_NAMES = ("сила", "ловкость", "интеллект", "харизма", "восприятие", "удача")
DEFAULT_STATS = {name: 5 for name in STAT_NAMES}
STAT_POINTS_TOTAL = 30
MISSION_MAX_PARTICIPANTS = 3
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
STAT_REWARD_CHANCE = 0.20
SHOP_BUY_PRICE_PER_LEVEL = 5
SHOP_SELL_PRICE_PER_LEVEL = 2
SHOP_SYSTEM_STOCK_SIZE = 6
SHOP_REFRESH_PERCENT = 0.25

SHOP_PREFIXES = (
    "Пепельный",
    "Лунный",
    "Серебряный",
    "Пороговый",
    "Каррокский",
    "Гильдейский",
    "Теневой",
    "Солевой",
    "Рунный",
    "Чернокаменный",
    "Зеркальный",
    "Латунный",
)

SHOP_BASE_ITEMS = (
    "фонарь привратника",
    "крюк с цепью",
    "плащ дозорного",
    "набор запорных пластин",
    "связка охранных гвоздей",
    "меловая печать",
    "ключ обходчика",
    "маска архивиста",
    "перчатка каменщика",
    "канделябр дознания",
    "оберег лестничных маршей",
    "фляга святой соли",
)

SHOP_SUFFIXES = (
    "из Старых Гнезд",
    "Восточного крыла",
    "Канцелярии Порогов",
    "Каррок Манора",
    "для подвальной стражи",
    "ночного обхода",
    "третьего пролета",
    "пепельной кладовой",
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


def normalize_stats(stats: dict[str, int] | None) -> dict[str, int]:
    if stats is None:
        return dict(DEFAULT_STATS)

    normalized = {name: int(stats.get(name, 0)) for name in STAT_NAMES}
    missing = [name for name, value in normalized.items() if value <= 0]
    if missing:
        raise ValueError(f"Каждая характеристика должна быть не меньше 1. Проверь: {', '.join(missing)}.")

    total = sum(normalized.values())
    if total != STAT_POINTS_TOTAL:
        raise ValueError(f"Сумма характеристик должна быть {STAT_POINTS_TOTAL}, сейчас {total}.")

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
    row = conn.execute("SELECT MIN(level) AS min_level, MAX(level) AS max_level FROM characters").fetchone()
    if row is None or row["min_level"] is None or row["max_level"] is None:
        return None
    return int(row["min_level"]), int(row["max_level"])


def mission_difficulty_bounds(conn: sqlite3.Connection) -> tuple[int, int] | None:
    ratings = character_power_ratings(conn)
    if not ratings:
        return None
    return max(1, min(ratings) - 1), max(ratings) + 2


def character_power_ratings(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT * FROM characters ORDER BY id").fetchall()
    return [character_power_rating(row_to_dict(row) or {}) for row in rows]


def character_power_rating(character: dict[str, Any]) -> int:
    stats = from_json(character.get("stats_json"), DEFAULT_STATS)
    average_stat = round(sum(int(value) for value in stats.values()) / max(1, len(stats)))
    inventory = from_json(character.get("inventory_json"), [])
    spells = from_json(character.get("spells_json"), [])
    pets = _entity_list(character, "pet_json", "pets_json")
    companions = _entity_list(character, "companion_json", "companions_json")
    mounts = _entity_list(character, "mount_json", "mounts_json")
    best_asset = _best_level([*inventory, *spells])
    best_helper = _best_level([*pets, *companions, *mounts])
    return int(character.get("level", 1)) + average_stat + best_asset + best_helper


def ensure_default_shop_items(conn: sqlite3.Connection) -> None:
    system_active_count = conn.execute(
        "SELECT COUNT(*) AS count FROM shop_items WHERE status = 'active' AND source != 'player_sale'"
    ).fetchone()["count"]
    if system_active_count >= SHOP_SYSTEM_STOCK_SIZE:
        return
    _add_system_shop_items(conn, SHOP_SYSTEM_STOCK_SIZE - int(system_active_count))


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

    refresh_count = max(1, (active_count + 3) // 4)
    rng = random.SystemRandom()
    selected_ids = [int(row["id"]) for row in rng.sample(active_system_rows, k=min(refresh_count, active_count))]
    conn.executemany(
        "UPDATE shop_items SET status = 'sold', sold_at = CURRENT_TIMESTAMP WHERE id = ?",
        [(item_id,) for item_id in selected_ids],
    )
    remaining_count = active_count - len(selected_ids)
    items_to_add = max(len(selected_ids), SHOP_SYSTEM_STOCK_SIZE - remaining_count)
    _add_system_shop_items(conn, items_to_add)
    return len(selected_ids)


def list_shop_items(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure_default_shop_items(conn)
    rows = conn.execute(
        """
        SELECT *
        FROM shop_items
        WHERE status = 'active'
        ORDER BY level, price, id
        """
    ).fetchall()
    return [row_to_dict(row) or {} for row in rows]


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
            INSERT INTO shop_items (asset_type, name, level, price, status, source)
            VALUES ('item', ?, ?, ?, 'active', 'system')
            """,
            (name, level, shop_buy_price(level)),
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
    rows = conn.execute("SELECT * FROM characters").fetchall()
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
    reward = {
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
        INSERT INTO shop_items (asset_type, name, level, price, status, source, seller_character_id)
        VALUES ('item', ?, ?, ?, 'active', 'player_sale', ?)
        """,
        (name, level, shop_buy_price(level), character["id"]),
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
        INSERT INTO shop_items (asset_type, name, level, price, status, source, seller_character_id)
        VALUES (?, ?, ?, ?, 'active', 'player_sale', ?)
        """,
        (entity_type, name, level, shop_buy_price(level), character["id"]),
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
    reward = {
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
        raise ValueError(
            f"У тебя нет {'питомца' if entity_type == 'pet' else 'маунта'} с таким именем. Проверь /allies или /sheet."
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
    initiator_mount_list = _entity_list(initiator, "mount_json", "mounts_json")
    target_mount_list = _entity_list(target, "mount_json", "mounts_json")
    moved_from_initiator, initiator_remaining = _split_inventory_by_uids(initiator_inventory, initiator_items)
    moved_from_target, target_remaining = _split_inventory_by_uids(target_inventory, target_items)
    moved_pets_from_initiator, initiator_pets_remaining = _split_entities_by_names(initiator_pet_list, initiator_pets)
    moved_pets_from_target, target_pets_remaining = _split_entities_by_names(target_pet_list, target_pets)
    moved_mounts_from_initiator, initiator_mounts_remaining = _split_entities_by_names(initiator_mount_list, initiator_mounts)
    moved_mounts_from_target, target_mounts_remaining = _split_entities_by_names(target_mount_list, target_mounts)
    if len(moved_from_initiator) != len(set(initiator_items)) or len(moved_from_target) != len(set(target_items)):
        raise ValueError("Один из предметов обмена больше не принадлежит участнику.")
    if len(moved_pets_from_initiator) != len(set(name.casefold() for name in initiator_pets)) or len(moved_pets_from_target) != len(set(name.casefold() for name in target_pets)):
        raise ValueError("Один из питомцев больше не принадлежит участнику.")
    if len(moved_mounts_from_initiator) != len(set(name.casefold() for name in initiator_mounts)) or len(moved_mounts_from_target) != len(set(name.casefold() for name in target_mounts)):
        raise ValueError("Один из маунтов больше не принадлежит участнику.")

    initiator_final_inventory = [*initiator_remaining, *moved_from_target]
    target_final_inventory = [*target_remaining, *moved_from_initiator]
    initiator_final_pets = [*initiator_pets_remaining, *moved_pets_from_target]
    target_final_pets = [*target_pets_remaining, *moved_pets_from_initiator]
    initiator_final_mounts = [*initiator_mounts_remaining, *moved_mounts_from_target]
    target_final_mounts = [*target_mounts_remaining, *moved_mounts_from_initiator]
    _validate_character_assets_unique(
        initiator,
        initiator_final_inventory,
        pets=initiator_final_pets,
        mounts=initiator_final_mounts,
    )
    _validate_character_assets_unique(
        target,
        target_final_inventory,
        pets=target_final_pets,
        mounts=target_final_mounts,
    )

    conn.execute(
        "UPDATE characters SET inventory_json = ?, pets_json = ?, mounts_json = ?, gold = ? WHERE id = ?",
        (
            to_json(initiator_final_inventory),
            to_json(initiator_final_pets),
            to_json(initiator_final_mounts),
            int(initiator["gold"]) - initiator_gold + target_gold,
            initiator["id"],
        ),
    )
    conn.execute(
        "UPDATE characters SET inventory_json = ?, pets_json = ?, mounts_json = ?, gold = ? WHERE id = ?",
        (
            to_json(target_final_inventory),
            to_json(target_final_pets),
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
    mounts: list[dict[str, Any]] | None = None,
) -> None:
    names: list[str] = []
    names.extend(item.get("name", "") for item in inventory if isinstance(item, dict))
    names.extend(spell.get("name", "") for spell in from_json(character["spells_json"], []) if isinstance(spell, dict))
    names.extend(entity.get("name", "") for entity in (pets if pets is not None else _entity_list(character, "pet_json", "pets_json")))
    names.extend(entity.get("name", "") for entity in _entity_list(character, "companion_json", "companions_json"))
    names.extend(entity.get("name", "") for entity in (mounts if mounts is not None else _entity_list(character, "mount_json", "mounts_json")))
    _validate_unique_names(names)


def _character_entity_collection(character: dict[str, Any], entity_type: str) -> list[dict[str, Any]]:
    if entity_type == "pet":
        return _entity_list(character, "pet_json", "pets_json")
    if entity_type == "mount":
        return _entity_list(character, "mount_json", "mounts_json")
    raise ValueError("Неизвестный тип сущности.")


def _entity_name(entity: dict[str, Any]) -> str:
    return str(entity.get("name", "")).strip().casefold()


def _best_level(assets: list[dict[str, Any]]) -> int:
    levels = [int(asset.get("level", 0)) for asset in assets if isinstance(asset, dict)]
    return max(levels, default=0)


def roll_reward(mission_difficulty: int) -> dict[str, Any]:
    rng = random.SystemRandom()
    roll = rng.random()
    if roll < STAT_REWARD_CHANCE:
        reward_type = "stat"
    elif roll < STAT_REWARD_CHANCE + RARE_REWARD_CHANCE:
        reward_type = rng.choice(["pet", "companion", "mount"])
    else:
        reward_type = rng.choice(["inventory", "spells", "gold"])

    return {
        "type": reward_type,
        "level": 1 if reward_type == "stat" else _roll_reward_level(rng, mission_difficulty),
        "rare": reward_type in {"stat", "pet", "companion", "mount"},
        "source": "backend_roll",
        "instruction": (
            "Choose one relevant stat and add +1. Use only if this character personally succeeds on a completed mission."
            if reward_type == "stat"
            else "Use only if this character personally succeeds on a completed mission."
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
    row = conn.execute("SELECT COUNT(*) AS count FROM characters").fetchone()
    character_count = int(row["count"]) if row else 0
    if character_count <= 0:
        return MIN_MISSIONS_PER_TURN
    return max(MIN_MISSIONS_PER_TURN, (character_count + MISSION_MAX_PARTICIPANTS - 1) // MISSION_MAX_PARTICIPANTS)


def reward_level_bounds(mission_difficulty: int) -> tuple[int, int]:
    return max(1, int(mission_difficulty) // 3), int(mission_difficulty)


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
    existing = row_to_dict(conn.execute("SELECT * FROM characters WHERE player_id = ?", (player["id"],)).fetchone())
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

    normalized_stats = normalize_stats(character_payload.get("stats"))
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

    existing = row_to_dict(conn.execute("SELECT * FROM characters WHERE player_id = ?", (player["id"],)).fetchone())
    if existing:
        conn.execute(
            """
            UPDATE characters
            SET name = ?, gender = ?, race = ?, description = ?, level = ?, xp = ?, gold = ?,
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
        conn.execute(
            """
            INSERT INTO missions (turn_id, title, description, difficulty, status, threat_json)
            VALUES (?, ?, ?, ?, 'open', ?)
            """,
            (
                turn_id,
                mission["title"],
                mission["description"],
                int(mission.get("difficulty", 1)),
                to_json(mission.get("threat", {})),
            ),
        )
    refresh_shop_for_new_turn(conn)
    conn.commit()
    return turn_id


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
    if len(missions) < MIN_MISSIONS_PER_TURN:
        raise ValueError(f"В ходе должно быть не меньше {MIN_MISSIONS_PER_TURN} миссий.")

    bounds = mission_difficulty_bounds(conn)
    if bounds is None:
        return

    min_difficulty, max_difficulty = bounds
    for index, mission in enumerate(missions, start=1):
        difficulty = int(mission.get("difficulty", 1))
        if difficulty < min_difficulty or difficulty > max_difficulty:
            raise ValueError(
                f"Сложность миссии #{index} должна быть от {min_difficulty} до {max_difficulty} "
                f"по текущим уровням персонажей."
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
    return [row_to_dict(row) or {} for row in rows]


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
        SELECT missions.id, missions.title
        FROM mission_participants
        JOIN missions ON missions.id = mission_participants.mission_id
        WHERE mission_participants.character_id = ?
          AND missions.turn_id = ?
        ORDER BY mission_participants.joined_at DESC
        LIMIT 1
        """,
        (character["id"], turn["id"]),
    ).fetchone()
    if joined_mission and int(joined_mission["id"]) != mission_id:
        raise ValueError(
            f"На этот ход ты уже записан на миссию #{joined_mission['id']}: {joined_mission['title']}. "
            "В альфе можно участвовать только в одной миссии за ход."
        )

    participant_count = conn.execute(
        "SELECT COUNT(*) AS count FROM mission_participants WHERE mission_id = ?",
        (mission_id,),
    ).fetchone()["count"]
    already_joined = conn.execute(
        "SELECT 1 FROM mission_participants WHERE mission_id = ? AND character_id = ?",
        (mission_id, character["id"]),
    ).fetchone()
    if participant_count >= MISSION_MAX_PARTICIPANTS and not already_joined:
        raise ValueError(f"На миссии уже максимум участников: {MISSION_MAX_PARTICIPANTS}.")

    conn.execute(
        """
        INSERT INTO mission_participants (mission_id, character_id)
        VALUES (?, ?)
        ON CONFLICT(mission_id, character_id) DO NOTHING
        """,
        (mission_id, character["id"]),
    )
    conn.commit()
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
            LEFT JOIN actions
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
                    "spells": from_json(character["spells_json"], []),
                    "skills": from_json(character["skills_json"], []),
                    "traits": from_json(character["traits_json"], []),
                    "inventory": from_json(character["inventory_json"], []),
                    "pets": _entity_list(character, "pet_json", "pets_json"),
                    "companions": _entity_list(character, "companion_json", "companions_json"),
                    "mounts": _entity_list(character, "mount_json", "mounts_json"),
                    "status": from_json(character["status_json"], {}),
                    "action_text": character["action_text"] or "",
                    "reward_roll": roll_reward(int(mission["difficulty"])),
                }
            )

        missions.append(
            {
                "mission_id": mission["id"],
                "title": mission["title"],
                "description": mission["description"],
                "difficulty": mission["difficulty"],
                "status": mission["status"],
                "threat": from_json(mission["threat_json"], {}),
                "participants": participants,
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
    }


def mark_exported(conn: sqlite3.Connection, turn_id: int, export_path: Path) -> None:
    conn.execute("UPDATE turns SET export_path = ? WHERE id = ?", (str(export_path), turn_id))
    conn.commit()


def apply_result_payload(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    turn_id = int(payload["turn_id"])
    turn = get_turn(conn, turn_id)
    if not turn:
        raise ValueError(f"Ход #{turn_id} не найден.")

    for mission_result in payload["mission_results"]:
        mission_id = int(mission_result["mission_id"])
        status = mission_result["status"]

        mission = row_to_dict(
            conn.execute("SELECT * FROM missions WHERE id = ? AND turn_id = ?", (mission_id, turn_id)).fetchone()
        )
        if not mission:
            raise ValueError(f"Миссия #{mission_id} не найдена в ходе #{turn_id}.")

        conn.execute("UPDATE missions SET status = ? WHERE id = ?", (status, mission_id))
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
            for change in player_result.get("changes", []):
                _validate_reward_change_allowed(mission_result, player_result, change)
                _apply_character_change(conn, turn_id, character_id, change, int(mission["difficulty"]))

    conn.execute("UPDATE turns SET status = 'resolved' WHERE id = ?", (turn_id,))
    conn.commit()


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


def _apply_character_change(
    conn: sqlite3.Connection,
    turn_id: int,
    character_id: int,
    change: dict[str, Any],
    mission_difficulty: int,
) -> None:
    allowed_scalar_fields = {"level", "xp", "gold"}
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
            if not _is_gm_override(change):
                _validate_reward_level(int(new_value) - int(old_value), mission_difficulty, "gold")

        if field in {"xp", "level", "gold"}:
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
        if not _is_gm_override(change):
            _validate_reward_level(int(reward["level"]), mission_difficulty, field)
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

    if field in {"pet", "familiar", "mount", "companion"}:
        normalized_field = "pet" if field == "familiar" else field
        column = _entity_list_column(normalized_field)
        old_value = _entity_list(character, f"{normalized_field}_json", column)
        new_value = _normalize_reward_object(change.get(field) or change.get(normalized_field) or change.get("value"))
        _ensure_unique_asset_name(character, new_value["name"])
        if not _is_gm_override(change):
            _validate_reward_level(int(new_value["level"]), mission_difficulty, normalized_field)
        updated_value = [*old_value, new_value]
        conn.execute(f"UPDATE characters SET {column} = ? WHERE id = ?", (to_json(updated_value), character_id))
        _log_change(conn, turn_id, character_id, normalized_field, old_value, updated_value, reason)
        return

    raise ValueError(f"Поле {field} пока нельзя менять через импорт результата.")


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


def _validate_reward_change_allowed(
    mission_result: dict[str, Any],
    player_result: dict[str, Any],
    change: dict[str, Any],
) -> None:
    reward_fields = {"gold", "inventory", "spells", "stat", "pet", "familiar", "companion", "mount"}
    if change.get("field") not in reward_fields:
        return
    if _is_gm_override(change):
        return
    if mission_result.get("status") != "completed":
        raise ValueError("Награды можно выдавать только за completed миссии.")
    if player_result.get("check", {}).get("success") is not True:
        raise ValueError("Награду можно выдать только персонажу, успешно прошедшему личную проверку.")
    if not player_result.get("reward_roll"):
        raise ValueError("Награда должна использовать backend reward_roll из экспорта хода.")
    _validate_change_matches_reward_roll(player_result, change)


def _is_gm_override(change: dict[str, Any]) -> bool:
    return change.get("gm_override") is True or change.get("source") == "gm_override"


def _validate_change_matches_reward_roll(player_result: dict[str, Any], change: dict[str, Any]) -> None:
    reward_roll = player_result.get("reward_roll")
    if not reward_roll:
        return

    expected_type = reward_roll.get("type")
    field = "pet" if change.get("field") == "familiar" else change.get("field")
    if expected_type != field:
        raise ValueError(f"Награда должна соответствовать backend reward_roll: {expected_type}.")

    expected_level = int(reward_roll.get("level", 0))
    if field == "gold":
        actual_level = int(change.get("delta", 0))
    elif field == "stat":
        stat_name = str(change.get("stat") or change.get("name") or "").strip().lower()
        if stat_name not in STAT_NAMES:
            raise ValueError(f"Награда stat должна указывать одну характеристику: {', '.join(STAT_NAMES)}.")
        actual_level = int(change.get("delta", 0))
    elif field == "inventory":
        actual_level = _reward_level_from_change_value(change.get("item") or change.get("value"))
    elif field == "spells":
        actual_level = _reward_level_from_change_value(change.get("spell") or change.get("value"))
    else:
        actual_level = _reward_level_from_change_value(change.get(change.get("field")) or change.get(field) or change.get("value"))

    if actual_level != expected_level:
        raise ValueError(f"Уровень награды должен соответствовать backend reward_roll: {expected_level}.")


def _reward_level_from_change_value(value: Any) -> int:
    if isinstance(value, dict):
        return int(value.get("level", 0))
    return 0


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
        normalized.append({"name": name, "level": level})
    return normalized


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


def mark_result_published(conn: sqlite3.Connection, result_id: int) -> None:
    conn.execute("UPDATE results SET published_at = CURRENT_TIMESTAMP WHERE id = ?", (result_id,))
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
