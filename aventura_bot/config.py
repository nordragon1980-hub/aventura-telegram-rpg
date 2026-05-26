from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    admin_telegram_ids: set[int]
    game_chat_id: int | None
    tanellorn_mini_app_enabled: bool
    tanellorn_mini_app_admin_only: bool
    tanellorn_mini_app_url: str
    mission_ui_mode: str
    database_path: Path
    exports_dir: Path
    imports_dir: Path
    backups_dir: Path
    seeds_dir: Path
    workbench_dir: Path
    art_dir: Path
    chronicle_dir: Path
    pending_imports_dir: Path
    processed_imports_dir: Path
    failed_imports_dir: Path


def _parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        ids.add(int(chunk))
    return ids


def _parse_optional_chat_id(raw: str) -> int | None:
    value = raw.strip()
    if not value:
        return None
    return int(value)


def _parse_bool(raw: str, default: bool) -> bool:
    value = raw.strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Некорректное логическое значение в env: {raw!r}. Используй true или false.")


def _parse_mission_ui_mode(raw: str) -> str:
    value = raw.strip().lower() or "legacy"
    if value not in {"legacy", "miniapp", "both"}:
        raise RuntimeError("MISSION_UI_MODE должен быть legacy, miniapp или both.")
    return value


def load_settings() -> Settings:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and add your BotFather token.")

    admin_ids = _parse_admin_ids(os.getenv("ADMIN_TELEGRAM_IDS", ""))
    if not admin_ids:
        raise RuntimeError("ADMIN_TELEGRAM_IDS is missing. Add your Telegram numeric user id to .env.")
    game_chat_id = _parse_optional_chat_id(os.getenv("GAME_CHAT_ID", ""))
    tanellorn_mini_app_enabled = _parse_bool(os.getenv("TANELLORN_MINI_APP_ENABLED", ""), False)
    tanellorn_mini_app_admin_only = _parse_bool(os.getenv("TANELLORN_MINI_APP_ADMIN_ONLY", ""), True)
    tanellorn_mini_app_url = os.getenv("TANELLORN_MINI_APP_URL", "").strip()
    mission_ui_mode = _parse_mission_ui_mode(os.getenv("MISSION_UI_MODE", ""))

    data_root_raw = os.getenv("DATA_ROOT", "").strip()
    data_root = Path(data_root_raw) if data_root_raw else None

    def _path_from_env(env_name: str, default_relative: str) -> Path:
        raw = os.getenv(env_name, "").strip()
        if raw:
            return Path(raw)
        if data_root is not None:
            return data_root / default_relative
        return Path("data") / default_relative

    database_path = Path(os.getenv("DATABASE_PATH", "").strip()) if os.getenv("DATABASE_PATH", "").strip() else (
        (data_root / "aventura.sqlite") if data_root is not None else Path("data/aventura.sqlite")
    )
    exports_dir = _path_from_env("EXPORTS_DIR", "exports")
    imports_dir = _path_from_env("IMPORTS_DIR", "imports")
    backups_dir = _path_from_env("BACKUPS_DIR", "backups")
    seeds_dir = _path_from_env("SEEDS_DIR", "seeds")
    workbench_dir = _path_from_env("WORKBENCH_DIR", "workbench")
    art_dir = _path_from_env("ART_DIR", "art")
    chronicle_dir = _path_from_env("CHRONICLE_DIR", "chronicle")
    pending_imports_dir = _path_from_env("PENDING_IMPORTS_DIR", "imports/pending")
    processed_imports_dir = _path_from_env("PROCESSED_IMPORTS_DIR", "imports/processed")
    failed_imports_dir = _path_from_env("FAILED_IMPORTS_DIR", "imports/failed")

    database_path.parent.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)
    imports_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)
    seeds_dir.mkdir(parents=True, exist_ok=True)
    workbench_dir.mkdir(parents=True, exist_ok=True)
    art_dir.mkdir(parents=True, exist_ok=True)
    chronicle_dir.mkdir(parents=True, exist_ok=True)
    pending_imports_dir.mkdir(parents=True, exist_ok=True)
    processed_imports_dir.mkdir(parents=True, exist_ok=True)
    failed_imports_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        telegram_bot_token=token,
        admin_telegram_ids=admin_ids,
        game_chat_id=game_chat_id,
        tanellorn_mini_app_enabled=tanellorn_mini_app_enabled,
        tanellorn_mini_app_admin_only=tanellorn_mini_app_admin_only,
        tanellorn_mini_app_url=tanellorn_mini_app_url,
        mission_ui_mode=mission_ui_mode,
        database_path=database_path,
        exports_dir=exports_dir,
        imports_dir=imports_dir,
        backups_dir=backups_dir,
        seeds_dir=seeds_dir,
        workbench_dir=workbench_dir,
        art_dir=art_dir,
        chronicle_dir=chronicle_dir,
        pending_imports_dir=pending_imports_dir,
        processed_imports_dir=processed_imports_dir,
        failed_imports_dir=failed_imports_dir,
    )
