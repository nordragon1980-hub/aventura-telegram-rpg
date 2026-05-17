from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


def connect(database_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL UNIQUE REFERENCES players(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            gender TEXT NOT NULL DEFAULT '',
            race TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            level INTEGER NOT NULL DEFAULT 1,
            xp INTEGER NOT NULL DEFAULT 0,
            gold INTEGER NOT NULL DEFAULT 0,
            hp INTEGER NOT NULL DEFAULT 10,
            max_hp INTEGER NOT NULL DEFAULT 10,
            stats_json TEXT NOT NULL DEFAULT '{}',
            spells_json TEXT NOT NULL DEFAULT '[]',
            skills_json TEXT NOT NULL DEFAULT '[]',
            traits_json TEXT NOT NULL DEFAULT '[]',
            inventory_json TEXT NOT NULL DEFAULT '[]',
            pet_json TEXT,
            companion_json TEXT,
            mount_json TEXT,
            pets_json TEXT NOT NULL DEFAULT '[]',
            companions_json TEXT NOT NULL DEFAULT '[]',
            mounts_json TEXT NOT NULL DEFAULT '[]',
            status_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            deadline TEXT,
            art_prompt TEXT,
            art_file_id TEXT,
            art_caption TEXT,
            status TEXT NOT NULL CHECK (status IN ('open', 'closed', 'resolved', 'published')),
            opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            closed_at TEXT,
            export_path TEXT
        );

        CREATE TABLE IF NOT EXISTS missions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            difficulty INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL CHECK (status IN ('open', 'ongoing', 'completed', 'failed')),
            threat_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mission_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id INTEGER NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'joined',
            joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (mission_id, character_id)
        );

        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
            mission_id INTEGER NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            action_text TEXT NOT NULL,
            submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (turn_id, mission_id, character_id)
        );

        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
            mission_id INTEGER NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            published_at TEXT,
            UNIQUE (turn_id, mission_id)
        );

        CREATE TABLE IF NOT EXISTS change_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
            character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
            field TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS city_chronicle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turn_id INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
            mission_id INTEGER NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
            turn_title TEXT NOT NULL,
            mission_title TEXT NOT NULL,
            status TEXT NOT NULL,
            public_summary TEXT NOT NULL,
            world_changes_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (turn_id, mission_id)
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            initiator_character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            target_character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            initiator_items_json TEXT NOT NULL DEFAULT '[]',
            target_items_json TEXT NOT NULL DEFAULT '[]',
            initiator_pets_json TEXT NOT NULL DEFAULT '[]',
            target_pets_json TEXT NOT NULL DEFAULT '[]',
            initiator_mounts_json TEXT NOT NULL DEFAULT '[]',
            target_mounts_json TEXT NOT NULL DEFAULT '[]',
            initiator_gold INTEGER NOT NULL DEFAULT 0,
            target_gold INTEGER NOT NULL DEFAULT 0,
            initiator_confirmed INTEGER NOT NULL DEFAULT 0,
            target_confirmed INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'cancelled')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type TEXT NOT NULL DEFAULT 'item',
            name TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            price INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL CHECK (status IN ('active', 'sold')) DEFAULT 'active',
            source TEXT NOT NULL DEFAULT 'shop',
            seller_character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            sold_at TEXT
        );

        CREATE TABLE IF NOT EXISTS arena_tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('draft', 'open', 'active', 'completed', 'cancelled')),
            rules_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS arena_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER REFERENCES arena_tournaments(id) ON DELETE SET NULL,
            character_a_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            character_b_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'resolved', 'cancelled')),
            action_a_text TEXT NOT NULL DEFAULT '',
            action_b_text TEXT NOT NULL DEFAULT '',
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS guild_farms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,
            resources_json TEXT NOT NULL DEFAULT '{}',
            buildings_json TEXT NOT NULL DEFAULT '[]',
            projects_json TEXT NOT NULL DEFAULT '[]',
            status_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS guild_farm_contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_farm_id INTEGER NOT NULL REFERENCES guild_farms(id) ON DELETE CASCADE,
            character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            resource_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    _ensure_column(conn, "characters", "gender", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "characters", "race", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "characters", "description", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "characters", "gold", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "characters", "spells_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "characters", "pet_json", "TEXT")
    _ensure_column(conn, "characters", "companion_json", "TEXT")
    _ensure_column(conn, "characters", "mount_json", "TEXT")
    _ensure_column(conn, "characters", "pets_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "characters", "companions_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "characters", "mounts_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "trades", "initiator_pets_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "trades", "target_pets_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "trades", "initiator_mounts_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "trades", "target_mounts_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "shop_items", "asset_type", "TEXT NOT NULL DEFAULT 'item'")
    _ensure_column(conn, "turns", "art_prompt", "TEXT")
    _ensure_column(conn, "turns", "art_file_id", "TEXT")
    _ensure_column(conn, "turns", "art_caption", "TEXT")
    _migrate_single_entity_to_list(conn, "pet_json", "pets_json")
    _migrate_single_entity_to_list(conn, "companion_json", "companions_json")
    _migrate_single_entity_to_list(conn, "mount_json", "mounts_json")
    _ensure_inventory_item_ids(conn)
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row["name"] for row in rows}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_single_entity_to_list(conn: sqlite3.Connection, single_column: str, list_column: str) -> None:
    rows = conn.execute(f"SELECT id, {single_column}, {list_column} FROM characters").fetchall()
    for row in rows:
        single = from_json(row[single_column], None)
        current_list = from_json(row[list_column], [])
        if single is None or current_list:
            continue
        conn.execute(
            f"UPDATE characters SET {list_column} = ? WHERE id = ?",
            (to_json([single]), row["id"]),
        )


def _ensure_inventory_item_ids(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, inventory_json FROM characters").fetchall()
    for row in rows:
        inventory = from_json(row["inventory_json"], [])
        changed = False
        for item in inventory:
            if isinstance(item, dict) and not str(item.get("uid", "")).strip():
                item["uid"] = uuid.uuid4().hex[:10]
                changed = True
        if changed:
            conn.execute("UPDATE characters SET inventory_json = ? WHERE id = ?", (to_json(inventory), row["id"]))


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def from_json(raw: str | None, fallback: Any) -> Any:
    if raw is None:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)
