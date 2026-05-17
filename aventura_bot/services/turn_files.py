from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_turn_yaml(path: Path) -> dict[str, Any]:
    payload = load_yaml(path)
    validate_turn_payload(payload)
    return payload


def load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    with path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)
    if not isinstance(payload, dict):
        raise ValueError("YAML-файл должен содержать объект.")
    return payload


def is_turn_payload(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("turn"), dict) and isinstance(payload.get("missions"), list)


def is_seed_payload(payload: dict[str, Any]) -> bool:
    if is_turn_payload(payload):
        return False
    return any(key in payload for key in ("turn", "theme", "generation", "mission_seeds", "fixed_missions"))


def validate_seed_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Seed-файл должен содержать объект YAML.")
    if "turn" in payload and not isinstance(payload["turn"], dict):
        raise ValueError("Блок turn в seed-файле должен быть объектом.")
    for key in ("mission_seeds", "fixed_missions"):
        if key in payload and not isinstance(payload[key], list):
            raise ValueError(f"{key} должен быть списком.")


def validate_turn_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Файл хода должен содержать объект YAML.")
    if not isinstance(payload.get("turn"), dict):
        raise ValueError("В файле должен быть блок turn.")
    if not payload["turn"].get("title"):
        raise ValueError("В turn.title нужно указать название хода.")
    if "art" in payload["turn"] and not isinstance(payload["turn"]["art"], dict):
        raise ValueError("turn.art должен быть объектом с prompt/caption.")
    if "art_prompt" in payload["turn"] and not isinstance(payload["turn"]["art_prompt"], str):
        raise ValueError("turn.art_prompt должен быть строкой.")
    if not isinstance(payload.get("missions"), list) or not payload["missions"]:
        raise ValueError("В файле должен быть непустой список missions.")
    if len(payload["missions"]) < 3:
        raise ValueError("В ходе должно быть не меньше 3 миссий.")

    for index, mission in enumerate(payload["missions"], start=1):
        if not isinstance(mission, dict):
            raise ValueError(f"Миссия #{index} должна быть объектом.")
        if not mission.get("title"):
            raise ValueError(f"У миссии #{index} нет title.")
        if not mission.get("description"):
            raise ValueError(f"У миссии #{index} нет description.")
        try:
            difficulty = int(mission.get("difficulty", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"У миссии #{index} difficulty должен быть числом.") from exc
        if difficulty < 1:
            raise ValueError(f"У миссии #{index} difficulty должен быть не меньше 1.")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def load_result_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    validate_result_payload(payload)
    return payload


def load_character_restore_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    validate_character_restore_payload(payload)
    return payload


def validate_result_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Файл результата должен содержать JSON-объект.")
    if not isinstance(payload.get("turn_id"), int):
        raise ValueError("result.json должен содержать числовой turn_id.")
    if not isinstance(payload.get("mission_results"), list):
        raise ValueError("result.json должен содержать список mission_results.")

    allowed_statuses = {"ongoing", "completed", "failed"}
    allowed_change_fields = {
        "level",
        "xp",
        "gold",
        "status",
        "stat",
        "inventory",
        "spells",
        "pet",
        "familiar",
        "companion",
        "mount",
    }
    for result in payload["mission_results"]:
        if not isinstance(result, dict):
            raise ValueError("Каждый mission_result должен быть объектом.")
        if not isinstance(result.get("mission_id"), int):
            raise ValueError("У mission_result должен быть числовой mission_id.")
        if result.get("status") not in allowed_statuses:
            raise ValueError(f"status должен быть одним из: {', '.join(sorted(allowed_statuses))}.")
        if "public_summary" in result and not isinstance(result.get("public_summary"), str):
            raise ValueError("public_summary должен быть строкой.")
        if "public_overview" in result and not isinstance(result.get("public_overview"), str):
            raise ValueError("public_overview должен быть строкой.")
        if not isinstance(result.get("player_results", []), list):
            raise ValueError("player_results должен быть списком.")
        for player_result in result.get("player_results", []):
            if not isinstance(player_result, dict):
                raise ValueError("Каждый player_result должен быть объектом.")
            if not isinstance(player_result.get("character_id"), int):
                raise ValueError("У player_result должен быть числовой character_id.")
            if not isinstance(player_result.get("changes", []), list):
                raise ValueError("changes должен быть списком.")
            for change in player_result.get("changes", []):
                if not isinstance(change, dict):
                    raise ValueError("Каждое изменение должно быть объектом.")
                if change.get("field") not in allowed_change_fields:
                    raise ValueError(
                        f"field изменения должен быть одним из: {', '.join(sorted(allowed_change_fields))}."
                    )


def validate_character_restore_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Файл восстановления должен содержать JSON-объект.")
    character = payload.get("character")
    if not isinstance(character, dict):
        raise ValueError("Файл восстановления должен содержать объект character.")
    if not isinstance(character.get("telegram_id"), int):
        raise ValueError("В character.telegram_id нужен числовой Telegram ID.")
    notify_enabled = character.get("notify_enabled", True)
    if not isinstance(notify_enabled, bool):
        raise ValueError("В character.notify_enabled нужно true или false.")

    required_strings = ("name", "gender", "race", "description")
    for key in required_strings:
        value = character.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"В character.{key} нужна непустая строка.")

    for key in ("level", "xp", "gold"):
        value = character.get(key)
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"В character.{key} нужно целое число не меньше 0.")

    stats = character.get("stats")
    if not isinstance(stats, dict):
        raise ValueError("В character.stats нужен объект характеристик.")

    for key in ("spells", "inventory", "pets", "companions", "mounts"):
        value = character.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"В character.{key} нужен список.")

    status = character.get("status", {})
    if not isinstance(status, (dict, list)):
        raise ValueError("В character.status нужен объект или список.")
