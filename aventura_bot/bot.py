from __future__ import annotations

import asyncio
import html
import json
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from aventura_bot.config import Settings, load_settings
from aventura_bot.db import connect, from_json, init_db, row_to_dict
from aventura_bot.services.game import (
    ACTION_TEXT_MAX_LENGTH,
    ACTION_TEXT_MIN_LENGTH,
    ASSET_NAME_MAX_LENGTH,
    CHARACTER_DESCRIPTION_MAX_LENGTH,
    CHARACTER_DESCRIPTION_MIN_LENGTH,
    CHARACTER_FIELD_MAX_LENGTH,
    CHARACTER_NAME_MAX_LENGTH,
    DEFAULT_STATS,
    DEADLY_TRIAL_DEATH_THRESHOLD,
    STAT_NAMES,
    apply_result_payload,
    build_turn_export,
    character_telegram_id,
    close_turn,
    create_character,
    create_turn_from_payload,
    get_character_change_log,
    mission_difficulty_bounds,
    mission_is_deadly_trial,
    get_character_for_player,
    get_open_turn,
    list_city_chronicle,
    list_public_roster,
    join_mission,
    list_player_telegram_ids,
    list_open_missions,
    mark_exported,
    mark_result_published,
    mission_is_phased_boss,
    mission_max_participants,
    mission_type_label,
    pending_publications,
    recommended_mission_count,
    refresh_shop_now,
    submit_action,
    set_turn_art,
    accept_trade,
    cancel_trade,
    create_craft_request,
    get_active_trade_for_player,
    buy_back_shop_item,
    buy_shop_item,
    build_heroes_snapshot,
    append_missions_to_open_turn,
    offer_trade_gold,
    offer_trade_item,
    offer_trade_mount,
    offer_trade_pet,
    list_shop_items,
    list_craft_assets,
    mark_craft_published,
    player_can_buy_back,
    pending_craft_publications,
    remove_trade_item,
    remove_trade_mount,
    remove_trade_pet,
    restore_character_from_payload,
    sell_mount,
    sell_pet,
    sell_inventory_item,
    start_trade,
    upsert_player,
)
from aventura_bot.services.mission_formatting import format_expandable_mission_details
from aventura_bot.services.turn_files import (
    is_seed_payload,
    is_turn_append_payload,
    is_turn_payload,
    load_character_restore_json,
    load_result_json,
    load_turn_yaml,
    load_yaml,
    validate_seed_payload,
    validate_turn_append_payload,
    validate_turn_payload,
    write_json,
)


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _is_admin(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    return bool(user and user.id in settings.admin_telegram_ids)


async def _require_private_chat(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


async def _safe_edit_message_text(message, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


def _db(context: ContextTypes.DEFAULT_TYPE):
    settings = _settings(context)
    return connect(settings.database_path)


MENU_MISSIONS = "Миссии"
MENU_MY_ACTION = "Мой ход"
MENU_HERO = "Герой"
MENU_SHOP = "Лавка"
MENU_CRAFT = "Крафт"
MENU_COMMANDS = "Команды"


def _main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(MENU_MISSIONS), KeyboardButton(MENU_MY_ACTION)],
            [KeyboardButton(MENU_HERO), KeyboardButton(MENU_SHOP)],
            [KeyboardButton(MENU_CRAFT), KeyboardButton(MENU_COMMANDS)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True,
        input_field_placeholder="Выбери действие или напиши команду...",
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        upsert_player(conn, update.effective_user.id, update.effective_user.username)
        character = get_character_for_player(conn, update.effective_user.id)
        open_turn = get_open_turn(conn)

    if character:
        text = f"Ты уже в гильдии Авентура: {character['name']}, {character['race']}."
        if open_turn:
            text += f"\nСейчас открыт ход #{open_turn['id']}: {open_turn['title']}. Миссии: /missions"
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())
    else:
        text = (
            "Добро пожаловать в Авентуру. Создай персонажа командой:\n"
            "/create_character\n"
            "Имя: ...\n"
            "Пол: ...\n"
            "Раса: ...\n"
            "Описание: ...\n"
            "Характеристики: сила=5 ловкость=5 интеллект=5 харизма=5 восприятие=5 удача=5\n"
            "Заклинание: ...\n"
            "Предметы: предмет1, предмет2, предмет3\n\n"
            "Питомца, спутника и маунта на старте нет."
        )
        if open_turn:
            text += f"\n\nСейчас уже идет ход #{open_turn['id']}: {open_turn['title']}. После создания героя сразу открой /missions."
        await update.message.reply_text(text, reply_markup=_main_menu_keyboard())


async def create_character_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return

    with _db(context) as conn:
        upsert_player(conn, update.effective_user.id, update.effective_user.username)
        existing_character = get_character_for_player(conn, update.effective_user.id)
    if existing_character:
        await update.message.reply_text(
            f"У тебя уже есть персонаж: {existing_character['name']}.\n"
            "В альфе повторное создание отключено. Если нужно что-то исправить, скажи мастеру."
        )
        return

    raw = _command_body(update.message.text or "")
    try:
        name, gender, race, description, stats, spell, items = _parse_character_payload(raw)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    with _db(context) as conn:
        try:
            character = create_character(
                conn,
                update.effective_user.id,
                name,
                gender,
                race,
                description,
                stats,
                spell,
                items,
            )
            open_turn = get_open_turn(conn)
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return

    text = (
        f"Персонаж создан: {character['name']}, {character['gender']}, {character['race']}.\n"
        f"Описание: {description}\n"
        f"Стартовое заклинание: {spell} ур. 1.\n"
        f"Предметы ур. 1: {', '.join(items)}."
    )
    if open_turn:
        text += f"\n\nСейчас идет ход #{open_turn['id']}: {open_turn['title']}. Посмотри доступные миссии командой /missions."
    await update.message.reply_text(text)


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        character = get_character_for_player(conn, update.effective_user.id)
    if not character:
        await update.message.reply_text("Персонаж еще не создан: /create_character Имя | Пол | Раса | описание | ...")
        return

    stats = json.dumps(from_json(character["stats_json"], {}), ensure_ascii=False)
    statuses = _format_statuses(from_json(character["status_json"], {}))
    await update.message.reply_text(
        f"{character['name']} / {character['gender']} / {character['race']}\n"
        f"{character['description']}\n"
        f"Уровень: {character['level']} | Золото: {character['gold']}\n"
        f"Состояния: {statuses}\n"
        f"Характеристики: {stats}\n\n"
        "Полный лист: /sheet"
    )


async def roster(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    with _db(context) as conn:
        roster_rows = list_public_roster(conn)
    if not roster_rows:
        await update.message.reply_text("В гильдии пока нет зарегистрированных героев.")
        return
    await update.message.reply_text(_format_public_roster(roster_rows))


async def sheet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        character = get_character_for_player(conn, update.effective_user.id)
    if not character:
        await update.message.reply_text("Персонаж еще не создан: /create_character Имя | Пол | Раса | описание | ...")
        return

    await update.message.reply_text(_format_character_sheet(character))


async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        character = get_character_for_player(conn, update.effective_user.id)
    if not character:
        await update.message.reply_text("Персонаж еще не создан.")
        return
    items = from_json(character["inventory_json"], [])
    await update.message.reply_text(
        _format_inventory(items),
        reply_markup=_inventory_keyboard(items) if items else None,
    )


async def spells(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        character = get_character_for_player(conn, update.effective_user.id)
    if not character:
        await update.message.reply_text("Персонаж еще не создан.")
        return
    await update.message.reply_text(_format_named_collection("Заклинания", from_json(character["spells_json"], [])))


async def allies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        character = get_character_for_player(conn, update.effective_user.id)
    if not character:
        await update.message.reply_text("Персонаж еще не создан.")
        return

    pets = _format_named_collection("Питомцы/фамильяры", _entity_list(character, "pet_json", "pets_json"))
    companions = _format_named_collection("Спутники/спутницы", _entity_list(character, "companion_json", "companions_json"))
    mounts = _format_named_collection("Маунты", _entity_list(character, "mount_json", "mounts_json"))
    await update.message.reply_text(
        f"{pets}\n\n{companions}\n\n{mounts}",
        reply_markup=_allies_keyboard(
            _entity_list(character, "pet_json", "pets_json"),
            _entity_list(character, "mount_json", "mounts_json"),
        ),
    )


async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        changes = get_character_change_log(conn, update.effective_user.id, limit=10)
    if not changes:
        await update.message.reply_text("Журнал изменений пока пуст.")
        return
    await update.message.reply_text(_format_change_log(changes))


async def export_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        character = get_character_for_player(conn, update.effective_user.id)
    if not character:
        await update.message.reply_text("Персонаж еще не создан.")
        return
    await update.message.reply_text(_format_character_sheet(character))


async def chat_id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    settings = _settings(context)
    if not _is_admin(update, settings):
        await update.message.reply_text("Эта команда доступна только админу.")
        return

    chat = update.effective_chat
    lines = [
        f"Chat ID: {chat.id}",
        f"Тип чата: {chat.type}",
    ]
    if settings.game_chat_id is not None:
        lines.append(f"Сейчас в GAME_CHAT_ID настроено: {settings.game_chat_id}")
    else:
        lines.append("GAME_CHAT_ID пока не настроен.")
    await update.message.reply_text("\n".join(lines))


def _format_character_sheet(character: dict) -> str:
    stats = _format_stats(from_json(character["stats_json"], {}))
    spells = _format_named_collection("Заклинания", from_json(character["spells_json"], []))
    items = _format_inventory(from_json(character["inventory_json"], []))
    statuses = _format_statuses(from_json(character["status_json"], {}))
    pets = _format_named_collection("Питомцы/фамильяры", _entity_list(character, "pet_json", "pets_json"))
    companions = _format_named_collection("Спутники/спутницы", _entity_list(character, "companion_json", "companions_json"))
    mounts = _format_named_collection("Маунты", _entity_list(character, "mount_json", "mounts_json"))
    return (
        f"{character['name']} / {character['gender']} / {character['race']}\n"
        f"Описание: {character['description'] or 'не указано'}\n"
        f"Уровень: {character['level']} | Золото: {character['gold']}\n"
        f"Состояния: {statuses}\n\n"
        f"Характеристики:\n{stats}\n\n"
        f"{spells}\n\n"
        f"{items}\n\n"
        f"{pets}\n\n"
        f"{companions}\n\n"
        f"{mounts}"
    )


async def missions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        mission_list = list_open_missions(conn)
    if not mission_list:
        await update.message.reply_text("Сейчас нет открытых миссий.")
        return

    await update.message.reply_text(_missions_intro_text(), parse_mode=ParseMode.HTML)
    for mission in mission_list:
        await update.message.reply_text(
            _format_mission_card(mission),
            reply_markup=_mission_keyboard(mission),
            parse_mode=ParseMode.HTML,
        )


def _missions_intro_text() -> str:
    return (
        "<b>Открытые миссии</b>\n"
        f"<i>Ответ свободный, главное чтобы было понятно, какую цель миссии решает герой. По длине ориентир: "
        f"{ACTION_TEXT_MIN_LENGTH}-{ACTION_TEXT_MAX_LENGTH} символов.</i>"
    )


def _format_mission_card(mission: dict) -> str:
    lines = [f"<b>Миссия #{mission['id']} — {html.escape(str(mission['title']))}</b>"]
    if mission_is_phased_boss(mission):
        lines.append("<b>Тип:</b> босс-миссия")
        lines.append(f"<b>Фаза:</b> {int(mission.get('phase', 1))}/{int(mission.get('max_phase', 1))}")
        lines.append(
            f"<i>{html.escape(str(mission.get('lock_warning') or 'Вступив в бой, герой останется в нем до победы или поражения.'))}</i>"
        )
        lines.append(f"<b>Участников:</b> до {mission_max_participants(mission)}")
    elif mission_is_deadly_trial(mission):
        lines.append(f"<b>Тип:</b> {mission_type_label('deadly_trial')}")
        lines.append(f"<b>Участников:</b> до {mission_max_participants(mission)}")
        lines.append(
            "<i>Высокий риск: при личном провале с отставанием "
            f"{DEADLY_TRIAL_DEATH_THRESHOLD}+ возможен посмертный исход. "
            "Действие должно прямо решать цели миссии.</i>"
        )
    lines.append(f"<b>Сложность:</b> {mission['difficulty']}")
    lines.append("")
    expanded_details = format_expandable_mission_details(mission)
    if expanded_details:
        lines.append(expanded_details)
    return "\n".join(lines) + "\n"


def _mission_keyboard(mission: dict) -> InlineKeyboardMarkup:
    if mission_is_phased_boss(mission):
        label = "Вступить в бой"
    elif mission_is_deadly_trial(mission):
        label = "Принять смертельное испытание"
    else:
        label = "Присоединиться к этой миссии"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"join:{mission['id']}")]]
    )


def _inventory_keyboard(items: list[dict]) -> InlineKeyboardMarkup | None:
    rows = []
    for item in items:
        uid = str(item.get("uid", "")).strip()
        if not uid:
            continue
        name = str(item.get("name", "без имени")).strip() or "без имени"
        try:
            sell_price = int(item.get("level", 1)) * 2
        except (TypeError, ValueError):
            sell_price = 2
        short_name = name if len(name) <= 28 else f"{name[:25]}..."
        rows.append(
            [
                InlineKeyboardButton(f"Продать за {sell_price}: {short_name}", callback_data=f"sell_item:{uid}"),
                InlineKeyboardButton("В обмен", callback_data=f"offer_item_inline:{uid}"),
            ]
        )
    return InlineKeyboardMarkup(rows) if rows else None


def _allies_keyboard(pets: list[dict], mounts: list[dict]) -> InlineKeyboardMarkup | None:
    rows = []
    for index, pet in enumerate(pets):
        name = str(pet.get("name", "без имени")).strip() or "без имени"
        level = int(pet.get("level", 1)) if str(pet.get("level", 1)).isdigit() else 1
        short_name = name if len(name) <= 24 else f"{name[:21]}..."
        rows.append(
            [
                InlineKeyboardButton(f"Продать питомца за {level * 2}: {short_name}", callback_data=f"sell_pet_inline:{index}"),
                InlineKeyboardButton("Питомца в обмен", callback_data=f"offer_pet_inline:{index}"),
            ]
        )
    for index, mount in enumerate(mounts):
        name = str(mount.get("name", "без имени")).strip() or "без имени"
        level = int(mount.get("level", 1)) if str(mount.get("level", 1)).isdigit() else 1
        short_name = name if len(name) <= 24 else f"{name[:21]}..."
        rows.append(
            [
                InlineKeyboardButton(f"Продать маунта за {level * 2}: {short_name}", callback_data=f"sell_mount_inline:{index}"),
                InlineKeyboardButton("Маунта в обмен", callback_data=f"offer_mount_inline:{index}"),
            ]
        )
    return InlineKeyboardMarkup(rows) if rows else None


def _buyback_keyboard(listing_id: int, price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"Выкупить обратно за {price}", callback_data=f"buyback:{listing_id}")]]
    )


def _short_button_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:max(0, limit - 3)]}..."


def _entity_name_by_index(character: dict, entity_type: str, index: int) -> str:
    if entity_type == "pet":
        entities = _entity_list(character, "pet_json", "pets_json")
    elif entity_type == "mount":
        entities = _entity_list(character, "mount_json", "mounts_json")
    else:
        return ""
    if index < 0 or index >= len(entities):
        return ""
    return str(entities[index].get("name", "")).strip()


def _action_template_keyboard(mission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Написать действие", callback_data=f"action_template:{mission_id}")]]
    )


def _craft_asset_keyboard(
    assets: list[dict],
    action_name: str,
    *,
    exclude_token: str | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    for asset in assets:
        token = str(asset.get("token") or "")
        if not token or token == exclude_token:
            continue
        name = _short_button_text(str(asset.get("name") or "без имени"), 42)
        rows.append(
            [
                InlineKeyboardButton(
                    f"ур. {asset.get('level', 1)} {name}",
                    callback_data=f"{action_name}:{token}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Отмена", callback_data="craft_cancel")])
    return InlineKeyboardMarkup(rows)


def _craft_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Крафт", callback_data="craft_confirm")],
            [InlineKeyboardButton("Отмена", callback_data="craft_cancel")],
        ]
    )


def _format_craft_asset(asset: dict) -> str:
    type_label = str(asset.get("type_label") or _asset_type_label(asset.get("type"))).strip()
    return f"{type_label}, ур. {asset.get('level', 1)}: {asset.get('name', 'без имени')}"


def _find_asset_by_token(assets: list[dict], token: str) -> dict | None:
    return next((asset for asset in assets if str(asset.get("token") or "") == token), None)


def _action_template_text(mission_title: str) -> str:
    return (
        f"Шаблон для миссии «{mission_title}»:\n\n"
        "/action Сначала мой герой выбирает одну из целей миссии и оценивает, с каким объектом, персонажем, местом или угрозой нужно взаимодействовать. "
        "Он выбирает понятный способ вмешаться и использует те сильные стороны, которые подходят именно к этой цели.\n\n"
        "Потом герой предпринимает основное действие: атакует, договаривается, исследует, защищает, чинит или обманывает - в зависимости от цели. "
        "Если уместно, он применяет предмет, заклинание или помощь союзника так, чтобы это было логично в контексте сцены.\n\n"
        "В конце герой старается закрепить результат: добить угрозу, спасти цель, добыть улику, удержать позицию или навязать свои условия. "
        "Если в миссии есть другие участники, нужно коротко учесть и их действия тоже."
    )


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    mission_id = _parse_numeric_command_arg(" ".join(context.args), allow_hash=True) if context.args else None
    if mission_id is None:
        await update.message.reply_text("Формат: /join 2. Можно писать и так: /join #2 или /join <ID:2>")
        return
    try:
        with _db(context) as conn:
            mission = join_mission(conn, update.effective_user.id, mission_id)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    switched_from = mission.get("switched_from")
    action_cleared = bool(mission.get("action_cleared"))
    if switched_from:
        notice = (
            f"Ты переназначен с миссии #{switched_from['id']} «{switched_from['title']}» "
            f"на миссию #{mission['id']} «{mission['title']}».\n"
        )
        if action_cleared:
            notice += "Твой прошлый текст хода для старой миссии сброшен, чтобы не перепутать сцены.\n"
        else:
            notice += "Текста хода на старую миссию у тебя еще не было, так что ничего не потерялось.\n"
        notice += (
            "Теперь отправь действие заново: /action текст\n"
            f"Пиши свободно, главное чтобы было понятно, что делает герой. По длине ориентир: {ACTION_TEXT_MIN_LENGTH}-{ACTION_TEXT_MAX_LENGTH} символов."
        )
        await update.message.reply_text(
            notice,
            reply_markup=_action_template_keyboard(int(mission["id"])),
        )
        return
    joined_label = (
        "Ты вступил в бой"
        if mission_is_phased_boss(mission)
        else "Ты принял смертельное испытание"
        if mission_is_deadly_trial(mission)
        else "Ты записан на миссию"
    )
    await update.message.reply_text(
        f"{joined_label}: {mission['title']}.\n"
        "Теперь отправь действие: /action текст\n"
        f"Пиши свободно, главное чтобы было понятно, что делает герой. По длине ориентир: {ACTION_TEXT_MIN_LENGTH}-{ACTION_TEXT_MAX_LENGTH} символов.",
        reply_markup=_action_template_keyboard(int(mission["id"])),
    )


async def action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    action_text = _command_body(update.message.text or "")
    if not action_text:
        await update.message.reply_text(
            f"Формат: /action текст. Опиши, какую цель миссии герой пытается выполнить и что именно он делает. "
            f"По длине ориентир: {ACTION_TEXT_MIN_LENGTH}-{ACTION_TEXT_MAX_LENGTH} символов."
        )
        return
    try:
        with _db(context) as conn:
            mission = submit_action(conn, update.effective_user.id, action_text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(f"Действие принято для миссии: {mission['title']}. Его можно заменить новой командой /action.")


async def craft_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    try:
        with _db(context) as conn:
            assets = list_craft_assets(conn, update.effective_user.id)
            open_turn = get_open_turn(conn)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    if not open_turn:
        await update.message.reply_text("Сейчас нет открытого хода. Крафт можно начать только во время хода.")
        return
    if len(assets) < 2:
        await update.message.reply_text("Для крафта нужны минимум два актива: основа и материал.")
        return
    context.user_data.pop("craft_base_token", None)
    context.user_data.pop("craft_material_token", None)
    await update.message.reply_text(
        "Выбери основу.\nОснова задает тип будущего результата.",
        reply_markup=_craft_asset_keyboard(assets, "craft_base"),
    )


async def my_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        row = conn.execute(
            """
            SELECT
                turns.id AS turn_id,
                turns.title AS turn_title,
                turns.deadline,
                missions.id AS mission_id,
                missions.title AS mission_title,
                missions.mission_type,
                missions.mission_subtype,
                missions.phase,
                missions.max_phase,
                missions.party_locked,
                missions.lock_warning,
                actions.action_text,
                actions.submitted_at
            FROM turns
            JOIN missions ON missions.turn_id = turns.id
            JOIN mission_participants ON mission_participants.mission_id = missions.id
            JOIN characters ON characters.id = mission_participants.character_id
            JOIN players ON players.id = characters.player_id
            LEFT JOIN actions
                ON actions.turn_id = turns.id
               AND actions.mission_id = missions.id
               AND actions.character_id = characters.id
            WHERE turns.status = 'open'
              AND players.telegram_id = ?
            ORDER BY mission_participants.joined_at DESC
            LIMIT 1
            """,
            (update.effective_user.id,),
        ).fetchone()
        open_turn = get_open_turn(conn)
        row = row_to_dict(row)

    if not open_turn:
        await update.message.reply_text("Сейчас нет открытого хода.")
        return
    if not row:
        await update.message.reply_text(
            f"Открыт ход #{open_turn['id']}: {open_turn['title']}\n"
            f"Дедлайн: {open_turn['deadline'] or 'не указан'}\n\n"
            "Ты пока не записан на миссию. Посмотри список: /missions"
        )
        return

    action_text = row["action_text"]
    if not action_text:
        mission_meta = _my_action_mission_meta(row)
        await update.message.reply_text(
            f"Ход #{row['turn_id']}: {row['turn_title']}\n"
            f"Дедлайн: {row['deadline'] or 'не указан'}\n"
            f"Миссия #{row['mission_id']}: {row['mission_title']}\n"
            f"{mission_meta}\n\n"
            "Действие еще не отправлено. Формат: /action текст"
        )
        return

    mission_meta = _my_action_mission_meta(row)
    await update.message.reply_text(
        f"Ход #{row['turn_id']}: {row['turn_title']}\n"
        f"Дедлайн: {row['deadline'] or 'не указан'}\n"
        f"Миссия #{row['mission_id']}: {row['mission_title']}\n"
        f"{mission_meta}\n"
        f"Отправлено: {row['submitted_at'] or 'время не записано'}\n\n"
        f"Твой текущий ход:\n{action_text}\n\n"
        "Можно заменить до дедлайна новой командой /action."
    )


def _my_action_mission_meta(row: dict) -> str:
    if str(row.get("mission_type") or "standard") == "boss" and str(row.get("mission_subtype") or "") == "phased":
        warning = row.get("lock_warning") or "Вступив в бой, герой останется в нем до победы или поражения."
        return f"Тип: босс-миссия\nФаза: {int(row.get('phase', 1))}/{int(row.get('max_phase', 1))}\n{warning}"
    return "Тип: стандартная миссия"


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    with _db(context) as conn:
        turn = get_open_turn(conn)
        mission_list = list_open_missions(conn)
        recommended_count = recommended_mission_count(conn)
        difficulty_bounds = mission_difficulty_bounds(conn)
    if not turn:
        if difficulty_bounds:
            await update.message.reply_text(
                "Открытого хода нет.\n"
                f"Рекомендуемое число миссий: {recommended_count}\n"
                f"Диапазон сложности: {difficulty_bounds[0]}-{difficulty_bounds[1]}"
            )
        else:
            await update.message.reply_text(
                "Открытого хода нет.\n"
                f"Рекомендуемое число миссий: {recommended_count}\n"
                "Диапазон сложности появится, когда в базе будет хотя бы один персонаж."
            )
        return
    difficulty_text = (
        f"{difficulty_bounds[0]}-{difficulty_bounds[1]}" if difficulty_bounds else "нет персонажей в базе"
    )
    await update.message.reply_text(
        f"Открыт ход #{turn['id']}: {turn['title']}\n"
        f"Дедлайн: {turn['deadline'] or 'не указан'}\n"
        f"Миссий: {len(mission_list)}\n"
        f"Рекомендуемое число миссий: {recommended_count}\n"
        f"Диапазон сложности: {difficulty_text}"
    )


async def refresh_shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    settings = _settings(context)
    if not _is_admin(update, settings):
        await update.message.reply_text("Обновлять лавку может только админ.")
        return
    with _db(context) as conn:
        result = refresh_shop_now(conn)
    await update.message.reply_text(
        "Лавка обновлена.\n"
        f"Пересчитано старых системных цен: {result['repriced']}\n"
        f"Ротировано системных товаров: {result['refreshed']}\n"
        f"Активных системных товаров сейчас: {result['active_system_items']}"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.message.document:
        return
    settings = _settings(context)
    if not _is_admin(update, settings):
        await update.message.reply_text("Загружать файлы хода и результата может только админ.")
        return

    document = update.message.document
    filename = document.file_name or "uploaded_file"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        await update.message.reply_text("Пришли .yaml/.yml для нового хода или .json для результата.")
        return

    telegram_file = await document.get_file()
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / filename
        await telegram_file.download_to_drive(custom_path=local_path)

        try:
            if suffix in {".yaml", ".yml"}:
                await _handle_yaml_upload(update, context, local_path)
            else:
                await _handle_json_upload(update, context, local_path)
        except Exception as exc:
            await update.message.reply_text(f"Файл не принят: {exc}")


async def handle_turn_art_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    settings = _settings(context)
    if not _is_admin(update, settings):
        await update.message.reply_text("Загружать арт хода может только админ.")
        return

    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        file_id = update.message.document.file_id
    if not file_id:
        await update.message.reply_text("Пришли картинку как фото или image-документ с подписью /turn_art.")
        return

    caption = _command_body(update.message.caption or "")
    write_json(
        _pending_turn_art_path(settings),
        {
            "telegram_file_id": file_id,
            "caption": caption or None,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    await update.message.reply_text(
        "Арт сохранен для следующего хода. Теперь загрузи turn.yaml, и бот разошлет картинку перед миссиями."
    )


async def _handle_yaml_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, local_path: Path) -> None:
    payload = load_yaml(local_path)
    if is_turn_payload(payload):
        validate_turn_payload(payload)
        await _handle_turn_yaml(update, context, local_path)
        return
    if is_turn_append_payload(payload):
        validate_turn_append_payload(payload)
        await _handle_turn_append_yaml(update, context, payload)
        return
    if is_seed_payload(payload):
        validate_seed_payload(payload)
        await _handle_seed_yaml(update, context, local_path, payload)
        return
    raise ValueError(
        "Не понял YAML: нужен turn.yaml с missions, append_open_turn.yaml с missions для добавления в текущий ход, "
        "или turn_seed.yaml с theme/generation/mission_seeds."
    )


async def _handle_json_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, local_path: Path) -> None:
    try:
        payload = load_result_json(local_path)
    except Exception as result_error:
        try:
            payload = load_character_restore_json(local_path)
        except Exception:
            raise result_error
        await _handle_character_restore_json(update, context, payload)
        return

    await _handle_result_json(update, context, local_path, payload=payload)


async def _handle_seed_yaml(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    local_path: Path,
    payload: dict,
) -> None:
    if not update.message:
        return
    settings = _settings(context)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    seed_path = settings.seeds_dir / f"turn_seed_{timestamp}.yaml"
    shutil.copy2(local_path, seed_path)
    workbench_path = _prepare_generation_workbench(settings, seed_path)
    title = payload.get("turn", {}).get("title", "без названия")
    await update.message.reply_text(
        f"Seed сохранен: {seed_path.name}\n"
        f"Тема: {title}\n"
        f"Workbench для Codex: {workbench_path}\n\n"
        "Теперь можно сказать Codex: сгенерируй ход по последнему seed."
    )


async def _handle_turn_yaml(update: Update, context: ContextTypes.DEFAULT_TYPE, local_path: Path) -> None:
    if not update.message:
        return
    settings = _settings(context)
    payload = load_turn_yaml(local_path)
    pending_art = _load_pending_turn_art(settings)
    art_file_id = (pending_art or {}).get("telegram_file_id") or _turn_art_file_id(payload)
    art_caption = (pending_art or {}).get("caption") or _turn_art_caption(payload) or payload["turn"]["title"]
    art_prompt = _turn_art_prompt(payload)
    with _db(context) as conn:
        turn_id = create_turn_from_payload(conn, payload)
        if art_file_id:
            set_turn_art(conn, turn_id, art_file_id, art_caption)
        mission_list = list_open_missions(conn)
        player_chat_ids = list_player_telegram_ids(conn)
    group_chat_id = settings.game_chat_id
    if pending_art and art_file_id:
        _pending_turn_art_path(settings).unlink(missing_ok=True)

    reply_lines = [f"Открыт ход #{turn_id}: {payload['turn']['title']}. Миссий: {len(mission_list)}."]
    if art_file_id:
        reply_lines.append("Арт хода будет отправлен игрокам перед миссиями.")
    elif art_prompt:
        reply_lines.append("В turn.yaml есть art prompt, но картинка не была загружена через /turn_art.")
    await update.message.reply_text("\n".join(reply_lines))

    if art_prompt and not art_file_id:
        await update.message.reply_text(f"Арт-промпт для генерации:\n\n{art_prompt[:3500]}")

    mission_intro = _missions_intro_text()
    if group_chat_id is not None:
        try:
            if art_file_id:
                await context.bot.send_photo(chat_id=group_chat_id, photo=art_file_id, caption=art_caption[:1024])
            await context.bot.send_message(chat_id=group_chat_id, text=mission_intro, parse_mode=ParseMode.HTML)
            for mission in mission_list:
                await context.bot.send_message(
                    chat_id=group_chat_id,
                    text=_format_mission_card(mission),
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            pass
    for chat_id in player_chat_ids:
        try:
            if art_file_id:
                await context.bot.send_photo(chat_id=chat_id, photo=art_file_id, caption=art_caption[:1024])
            await context.bot.send_message(chat_id=chat_id, text=mission_intro, parse_mode=ParseMode.HTML)
            for mission in mission_list:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=_format_mission_card(mission),
                    reply_markup=_mission_keyboard(mission),
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            continue


async def _handle_turn_append_yaml(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: dict) -> None:
    if not update.message:
        return
    missions_payload = payload["missions"]
    settings = _settings(context)
    with _db(context) as conn:
        turn, created_missions = append_missions_to_open_turn(conn, missions_payload)
        player_chat_ids = list_player_telegram_ids(conn)
    group_chat_id = settings.game_chat_id

    await update.message.reply_text(
        f"В открытый ход #{turn['id']} «{turn['title']}» добавлено миссий: {len(created_missions)}."
    )

    intro = "<b>В ход добавлены новые миссии</b>\n<i>Можно брать их сразу, ход не перезапускался.</i>"
    if group_chat_id is not None:
        try:
            await context.bot.send_message(chat_id=group_chat_id, text=intro, parse_mode=ParseMode.HTML)
            for mission in created_missions:
                await context.bot.send_message(
                    chat_id=group_chat_id,
                    text=_format_mission_card(mission),
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            pass
    for chat_id in player_chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=intro, parse_mode=ParseMode.HTML)
            for mission in created_missions:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=_format_mission_card(mission),
                    reply_markup=_mission_keyboard(mission),
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            continue


async def _handle_result_json(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    local_path: Path,
    payload: dict | None = None,
) -> None:
    if not update.message:
        return
    settings = _settings(context)
    if payload is None:
        payload = load_result_json(local_path)
    payload = await _import_and_publish_result(context.application, settings, local_path, publish=True)
    await update.message.reply_text(f"Результат для хода #{payload['turn_id']} импортирован и опубликован.")


async def _handle_character_restore_json(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: dict) -> None:
    if not update.message:
        return
    settings = _settings(context)
    _backup_database(settings)
    with _db(context) as conn:
        restored = restore_character_from_payload(conn, payload)
    await update.message.reply_text(
        f"Персонаж восстановлен: {restored['name']}.\n"
        f"Уровень: {restored['level']} | Золото: {restored['gold']}."
    )


async def export_turn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    settings = _settings(context)
    if not _is_admin(update, settings):
        await update.message.reply_text("Экспортировать ход может только админ.")
        return

    with _db(context) as conn:
        turn = get_open_turn(conn)
    if not turn:
        await update.message.reply_text("Открытого хода нет.")
        return

    export_path = await _close_and_export_turn(context.application, settings, turn["id"], notify_admins=False)
    await update.message.reply_document(document=export_path, caption=f"Ход #{turn['id']} закрыт и экспортирован.")


async def publish_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    settings = _settings(context)
    if not _is_admin(update, settings):
        await update.message.reply_text("Публиковать результаты может только админ.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Формат: /publish_results <turn_id>")
        return

    turn_id = int(context.args[0])
    public_count, personal_count = await _publish_results_for_turn(context.application, turn_id)
    await update.message.reply_text(
        f"Опубликовано общих итогов: {public_count}. Персональных результатов: {personal_count}."
    )


async def chronicle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    settings = _settings(context)
    if not _is_admin(update, settings):
        await update.message.reply_text("Смотреть городскую хронику через бота может только админ.")
        return

    with _db(context) as conn:
        entries = list_city_chronicle(conn, limit=10)
    if not entries:
        await update.message.reply_text("Городская хроника пока пуста.")
        return
    await update.message.reply_text(_format_chronicle_entries(entries))


async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        items = list_shop_items(conn)
        character = get_character_for_player(conn, update.effective_user.id)
        can_buy_back_ids = {int(item["id"]) for item in items if player_can_buy_back(conn, update.effective_user.id, int(item["id"]))}
    gold = character["gold"] if character else 0
    await update.message.reply_text(
        _format_shop_items(items, int(gold), can_buy_back_ids=can_buy_back_ids),
        reply_markup=_shop_keyboard(items, can_buy_back_ids=can_buy_back_ids),
    )


async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    item_id = _parse_numeric_command_arg(" ".join(context.args), allow_hash=True) if context.args else None
    if item_id is None:
        await update.message.reply_text("Формат: /buy 7. Можно писать и так: /buy #7 или /buy <ID:7>")
        return
    try:
        with _db(context) as conn:
            result = buy_shop_item(conn, update.effective_user.id, item_id)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    item = result["item"]
    asset_label = _asset_type_label(result.get("asset_type", "item"))
    await update.message.reply_text(
        f"Куплено: {asset_label} {item['name']} ур. {item['level']} за {result['price']} дублонов.\n"
        f"Осталось дублонов: {result['gold']}."
    )


async def sell_item_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /sell_item abc123. Можно писать и так: /sell_item ID:abc123 или /sell_item <ID:abc123>.")
        return
    item_uid = _parse_item_uid_arg(" ".join(context.args))
    try:
        with _db(context) as conn:
            result = sell_inventory_item(conn, update.effective_user.id, item_uid)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    item = result["item"]
    await update.message.reply_text(
        f"Продано: {item.get('name', 'без имени')} ур. {item.get('level', 1)} за {result['price']} дублонов.\n"
        f"Теперь дублонов: {result['gold']}.",
        reply_markup=_buyback_keyboard(int(result["listing_id"]), int(result["buyback_price"])),
    )


async def sell_pet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /sell_pet <имя питомца>. Имя видно в /allies или /sheet.")
        return
    try:
        with _db(context) as conn:
            result = sell_pet(conn, update.effective_user.id, " ".join(context.args))
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    item = result["item"]
    await update.message.reply_text(
        f"Продан питомец: {item.get('name', 'без имени')} ур. {item.get('level', 1)} за {result['price']} дублонов.\n"
        f"Теперь дублонов: {result['gold']}.",
        reply_markup=_buyback_keyboard(int(result["listing_id"]), int(result["buyback_price"])),
    )


async def sell_mount_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /sell_mount <имя маунта>. Имя видно в /allies или /sheet.")
        return
    try:
        with _db(context) as conn:
            result = sell_mount(conn, update.effective_user.id, " ".join(context.args))
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    item = result["item"]
    await update.message.reply_text(
        f"Продан маунт: {item.get('name', 'без имени')} ур. {item.get('level', 1)} за {result['price']} дублонов.\n"
        f"Теперь дублонов: {result['gold']}.",
        reply_markup=_buyback_keyboard(int(result["listing_id"]), int(result["buyback_price"])),
    )


async def trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /trade @username или /trade ИмяПерсонажа")
        return
    target_query = " ".join(context.args)
    try:
        with _db(context) as conn:
            trade = start_trade(conn, update.effective_user.id, target_query)
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(summary)
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, f"Тебе предложили обмен.\n\n{summary}")


async def offer_item_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /offer_item abc123. Можно писать и так: /offer_item ID:abc123 или /offer_item <ID:abc123>.")
        return
    item_uid = _parse_item_uid_arg(" ".join(context.args))
    try:
        with _db(context) as conn:
            trade = offer_trade_item(conn, update.effective_user.id, item_uid)
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(summary)
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, f"Обмен обновлен.\n\n{summary}")


async def offer_pet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /offer_pet <имя питомца>. Имя видно в /allies или /sheet.")
        return
    try:
        with _db(context) as conn:
            trade = offer_trade_pet(conn, update.effective_user.id, " ".join(context.args))
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(summary)
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, f"Обмен обновлен.\n\n{summary}")


async def offer_mount_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /offer_mount <имя маунта>. Имя видно в /allies или /sheet.")
        return
    try:
        with _db(context) as conn:
            trade = offer_trade_mount(conn, update.effective_user.id, " ".join(context.args))
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(summary)
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, f"Обмен обновлен.\n\n{summary}")


async def remove_item_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /remove_item abc123. Можно писать и так: /remove_item ID:abc123 или /remove_item <ID:abc123>.")
        return
    item_uid = _parse_item_uid_arg(" ".join(context.args))
    try:
        with _db(context) as conn:
            trade = remove_trade_item(conn, update.effective_user.id, item_uid)
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(summary)
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, f"Обмен обновлен.\n\n{summary}")


async def remove_pet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /remove_pet <имя питомца>")
        return
    try:
        with _db(context) as conn:
            trade = remove_trade_pet(conn, update.effective_user.id, " ".join(context.args))
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(summary)
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, f"Обмен обновлен.\n\n{summary}")


async def remove_mount_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args:
        await update.message.reply_text("Формат: /remove_mount <имя маунта>")
        return
    try:
        with _db(context) as conn:
            trade = remove_trade_mount(conn, update.effective_user.id, " ".join(context.args))
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(summary)
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, f"Обмен обновлен.\n\n{summary}")


async def offer_gold_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Формат: /offer_gold <количество дублонов>. Можно указать 0.")
        return
    try:
        with _db(context) as conn:
            trade = offer_trade_gold(conn, update.effective_user.id, int(context.args[0]))
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(summary)
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, f"Обмен обновлен.\n\n{summary}")


async def trade_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        trade = get_active_trade_for_player(conn, update.effective_user.id)
        if not trade:
            await update.message.reply_text("У тебя нет активного обмена.")
            return
        summary = _format_trade(conn, trade)
    await update.message.reply_text(summary)


async def accept_trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    try:
        with _db(context) as conn:
            trade, completed = accept_trade(conn, update.effective_user.id)
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    if completed:
        text = f"Обмен завершен.\n\n{summary}"
    else:
        text = f"Ты подтвердил обмен. Ждем подтверждение второго участника.\n\n{summary}"
    await update.message.reply_text(text)
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, text if completed else f"Второй участник подтвердил обмен.\n\n{summary}")


async def cancel_trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    try:
        with _db(context) as conn:
            trade = cancel_trade(conn, update.effective_user.id)
            summary = _format_trade(conn, trade)
            participant_ids = _trade_participant_telegram_ids(conn, trade)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(f"Обмен отменен.\n\n{summary}")
    await _notify_trade_partner(context, participant_ids, update.effective_user.id, f"Обмен отменен.\n\n{summary}")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Игрок:\n"
        "/start\n"
        "/create_character + поля Имя/Пол/Раса/Описание/Характеристики/Заклинание/Предметы\n"
        "/profile\n"
        "/roster\n"
        "/sheet\n"
        "/inventory\n"
        "/spells\n"
        "/allies\n"
        "/log\n"
        "/missions\n"
        "/join <id>\n"
        "/action <текст>\n"
        "/my_action\n"
        "/craft\n"
        "/shop\n"
        "/buy <ID товара>\n"
        "/sell_item <ID предмета>\n"
        "/sell_pet <имя питомца>\n"
        "/sell_mount <имя маунта>\n"
        "/trade @username\n"
        "/offer_item <ID>\n"
        "/offer_pet <имя>\n"
        "/offer_mount <имя>\n"
        "/remove_item <ID>\n"
        "/remove_pet <имя>\n"
        "/remove_mount <имя>\n"
        "/offer_gold <дублоны>\n"
        "/trade_status\n"
        "/accept_trade\n"
        "/cancel_trade\n\n"
        "Админ:\n"
        "загрузить арт фото с подписью /turn_art\n"
        "загрузить turn.yaml\n"
        "/chat_id\n"
        "показать id текущего чата для настройки игровой группы\n"
        "/refresh_shop\n"
        "/export_turn\n"
        "загрузить result.json\n"
        "/publish_results <turn_id>\n"
        "/chronicle\n\n"
        "Нижние кнопки помогают не помнить команды наизусть: "
        "Миссии, Мой ход, Герой, Лавка, Крафт, Команды.\n"
        "Для действий с параметрами можно писать свободнее, например: /join #3, /buy <ID:7>, /sell_item ID:abc123 или /offer_pet Имя.\n"
        "Создание героя тоже стало мягче: можно не использовать |, а просто писать поля с новой строки.",
        reply_markup=_main_menu_keyboard(),
    )


async def menu_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not await _require_private_chat(update):
        return

    text = (update.message.text or "").strip()
    if text == MENU_MISSIONS:
        await missions(update, context)
        return
    if text == MENU_MY_ACTION:
        await my_action(update, context)
        return
    if text == MENU_HERO:
        await sheet(update, context)
        return
    if text == MENU_SHOP:
        await shop_cmd(update, context)
        return
    if text == MENU_CRAFT:
        await craft_cmd(update, context)
        return
    if text == MENU_COMMANDS:
        await help_cmd(update, context)
        return


async def inline_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return
    if update.effective_chat and update.effective_chat.type != "private":
        await query.answer("Эта кнопка работает только в личке с ботом.", show_alert=True)
        return

    data = query.data or ""
    action_name, _, raw_id = data.partition(":")
    if action_name in {"join", "action_template", "buy", "buyback"} and not raw_id.isdigit():
        await query.answer("Не понял кнопку.", show_alert=True)
        return

    if action_name == "join":
        try:
            with _db(context) as conn:
                mission = join_mission(conn, user.id, int(raw_id))
            switched_from = mission.get("switched_from")
            action_cleared = bool(mission.get("action_cleared"))
            if switched_from:
                answer_text = (
                    "Бой обновлен."
                    if mission_is_phased_boss(mission)
                    else "Смертельное испытание обновлено."
                    if mission_is_deadly_trial(mission)
                    else "Миссия обновлена."
                )
            else:
                answer_text = (
                    "Ты вступил в бой."
                    if mission_is_phased_boss(mission)
                    else "Ты принял смертельное испытание."
                    if mission_is_deadly_trial(mission)
                    else "Ты записан на миссию."
                )
            await query.answer(answer_text)
            if query.message:
                await _safe_edit_message_text(
                    query.message,
                    _format_mission_card(mission)
                    + (
                        "\nТы уже в этом бою."
                        if mission_is_phased_boss(mission)
                        else "\nТы уже принял это смертельное испытание."
                        if mission_is_deadly_trial(mission)
                        else "\nТы уже записан на эту миссию."
                    ),
                    reply_markup=None,
                    parse_mode=ParseMode.HTML,
                )
                if switched_from:
                    text = (
                        f"Ты переназначен с миссии #{switched_from['id']} «{switched_from['title']}» "
                        f"на миссию #{mission['id']} «{mission['title']}».\n"
                    )
                    if action_cleared:
                        text += "Твой прошлый текст хода для старой миссии сброшен, чтобы не перепутать сцены.\n"
                    else:
                        text += "На старой миссии текста хода у тебя еще не было, так что ничего не потерялось.\n"
                    text += (
                        "Теперь отправь действие заново: /action текст\n"
                        f"Пиши свободно, главное чтобы было понятно, что делает герой. По длине ориентир: {ACTION_TEXT_MIN_LENGTH}-{ACTION_TEXT_MAX_LENGTH} символов."
                    )
                else:
                    joined_label = (
                        "Ты вступил в бой"
                        if mission_is_phased_boss(mission)
                        else "Ты принял смертельное испытание"
                        if mission_is_deadly_trial(mission)
                        else "Ты записан на миссию"
                    )
                    text = (
                        f"{joined_label}: {mission['title']}.\n"
                        "Теперь отправь действие: /action текст\n"
                        f"Пиши свободно, главное чтобы было понятно, что делает герой. По длине ориентир: {ACTION_TEXT_MIN_LENGTH}-{ACTION_TEXT_MAX_LENGTH} символов."
                    )
                await query.message.reply_text(
                    text,
                    reply_markup=_action_template_keyboard(int(mission["id"])),
                )
            return
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return

    if action_name == "action_template":
        with _db(context) as conn:
            mission_row = conn.execute("SELECT id, title FROM missions WHERE id = ?", (int(raw_id),)).fetchone()
        if not mission_row:
            await query.answer("Миссия не найдена.", show_alert=True)
            return
        await query.answer("Шаблон отправлен.")
        if query.message:
            await query.message.reply_text(_action_template_text(str(mission_row["title"])))
        return

    if action_name == "craft_base":
        try:
            with _db(context) as conn:
                assets = list_craft_assets(conn, user.id)
            base = _find_asset_by_token(assets, raw_id)
            if not base:
                raise ValueError("Основа уже не найдена. Открой крафт заново.")
            if len(assets) < 2:
                raise ValueError("Для крафта нужны минимум два актива.")
            context.user_data["craft_base_token"] = raw_id
            context.user_data.pop("craft_material_token", None)
            await query.answer("Основа выбрана.")
            if query.message:
                await _safe_edit_message_text(
                    query.message,
                    "Выбери материал.\nМатериал будет поглощен и изменит основу.",
                    reply_markup=_craft_asset_keyboard(assets, "craft_material", exclude_token=raw_id),
                )
            return
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return

    if action_name == "craft_material":
        base_token = str(context.user_data.get("craft_base_token") or "")
        if not base_token:
            await query.answer("Сначала выбери основу.", show_alert=True)
            return
        try:
            with _db(context) as conn:
                assets = list_craft_assets(conn, user.id)
            base = _find_asset_by_token(assets, base_token)
            material = _find_asset_by_token(assets, raw_id)
            if not base or not material:
                raise ValueError("Один из активов уже не найден. Открой крафт заново.")
            if base_token == raw_id:
                raise ValueError("Материал должен отличаться от основы.")
            context.user_data["craft_material_token"] = raw_id
            text = (
                "Подтвердить крафт?\n\n"
                f"Основа:\n{_format_craft_asset(base)}\n\n"
                f"Материал:\n{_format_craft_asset(material)}\n\n"
                "Оба актива исчезнут сейчас.\n"
                "Результат будет создан при обработке следующего хода."
            )
            await query.answer("Материал выбран.")
            if query.message:
                await _safe_edit_message_text(query.message, text, reply_markup=_craft_confirm_keyboard())
            return
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return

    if action_name == "craft_confirm":
        base_token = str(context.user_data.get("craft_base_token") or "")
        material_token = str(context.user_data.get("craft_material_token") or "")
        if not base_token or not material_token:
            await query.answer("Выбери основу и материал заново.", show_alert=True)
            return
        try:
            with _db(context) as conn:
                request = create_craft_request(conn, user.id, base_token, material_token)
            context.user_data.pop("craft_base_token", None)
            context.user_data.pop("craft_material_token", None)
            await query.answer("Крафт начат.")
            if query.message:
                text = (
                    "Крафт начат.\n\n"
                    f"Основа: {_format_craft_asset(request['base'])}\n"
                    f"Материал: {_format_craft_asset(request['material'])}\n\n"
                    "Основа и материал потрачены.\n"
                    "Результат появится после обработки хода, вместе с итогами миссий."
                )
                await _safe_edit_message_text(query.message, text, reply_markup=None)
            return
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return

    if action_name == "craft_cancel":
        context.user_data.pop("craft_base_token", None)
        context.user_data.pop("craft_material_token", None)
        await query.answer("Крафт отменен.")
        if query.message:
            await _safe_edit_message_text(query.message, "Крафт отменен.", reply_markup=None)
        return

    if action_name == "buy":
        try:
            with _db(context) as conn:
                result = buy_shop_item(conn, user.id, int(raw_id))
                items = list_shop_items(conn)
                character = get_character_for_player(conn, user.id)
                can_buy_back_ids = {int(item["id"]) for item in items if player_can_buy_back(conn, user.id, int(item["id"]))}
            gold = int(character["gold"]) if character else int(result["gold"])
            item = result["item"]
            await query.answer("Покупка прошла.")
            if query.message:
                reply_markup = _shop_keyboard(items, can_buy_back_ids=can_buy_back_ids) if items else None
                await _safe_edit_message_text(
                    query.message,
                    _format_shop_items(items, gold, can_buy_back_ids=can_buy_back_ids),
                    reply_markup=reply_markup,
                )
                asset_label = _asset_type_label(result.get("asset_type", "item"))
                await query.message.reply_text(
                    f"Куплено: {asset_label} {item['name']} ур. {item['level']} за {result['price']} дублонов.\n"
                    f"Осталось дублонов: {gold}."
                )
            return
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return

    if action_name == "buyback":
        try:
            with _db(context) as conn:
                result = buy_back_shop_item(conn, user.id, int(raw_id))
                items = list_shop_items(conn)
                character = get_character_for_player(conn, user.id)
                can_buy_back_ids = {int(item["id"]) for item in items if player_can_buy_back(conn, user.id, int(item["id"]))}
            gold = int(character["gold"]) if character else int(result["gold"])
            item = result["item"]
            await query.answer("Товар выкуплен обратно.")
            if query.message:
                reply_markup = _shop_keyboard(items, can_buy_back_ids=can_buy_back_ids) if items else None
                await _safe_edit_message_text(
                    query.message,
                    _format_shop_items(items, gold, can_buy_back_ids=can_buy_back_ids),
                    reply_markup=reply_markup,
                )
                asset_label = _asset_type_label(result.get("asset_type", "item"))
                await query.message.reply_text(
                    f"Выкуплено обратно: {asset_label} {item['name']} ур. {item['level']} за {result['price']} дублонов.\n"
                    f"Теперь у тебя {gold} дублонов."
                )
            return
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return

    if action_name == "sell_item":
        try:
            with _db(context) as conn:
                result = sell_inventory_item(conn, user.id, raw_id)
                character = get_character_for_player(conn, user.id)
            items = from_json(character["inventory_json"], []) if character else []
            gold = int(character["gold"]) if character else int(result["gold"])
            item = result["item"]
            await query.answer("Предмет продан.")
            if query.message:
                reply_markup = _inventory_keyboard(items) if items else None
                await _safe_edit_message_text(query.message, _format_inventory(items), reply_markup=reply_markup)
                await query.message.reply_text(
                    f"Продано: {item.get('name', 'без имени')} ур. {item.get('level', 1)} за {result['price']} дублонов.\n"
                    f"Теперь у тебя {gold} дублонов.",
                    reply_markup=_buyback_keyboard(int(result["listing_id"]), int(result["buyback_price"])),
                )
            return
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return

    if action_name == "offer_item_inline":
        try:
            with _db(context) as conn:
                trade = get_active_trade_for_player(conn, user.id)
                if not trade:
                    raise ValueError("Сначала открой обмен: /trade @username")
                trade = offer_trade_item(conn, user.id, raw_id)
                summary = _format_trade(conn, trade)
                participant_ids = _trade_participant_telegram_ids(conn, trade)
            await query.answer("Предмет добавлен в обмен.")
            if query.message:
                await query.message.reply_text(f"Предмет добавлен в обмен.\n\n{summary}")
            await _notify_trade_partner(
                context,
                participant_ids,
                user.id,
                f"Состав обмена обновлен.\n\n{summary}",
            )
            return
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return

    if action_name in {"sell_pet_inline", "offer_pet_inline", "sell_mount_inline", "offer_mount_inline"}:
        if not raw_id.isdigit():
            await query.answer("Не понял кнопку.", show_alert=True)
            return
        entity_type = "pet" if "pet" in action_name else "mount"
        entity_index = int(raw_id)
        try:
            with _db(context) as conn:
                character = get_character_for_player(conn, user.id)
                if not character:
                    raise ValueError("Персонаж не найден.")
                entity_name = _entity_name_by_index(character, entity_type, entity_index)
                if not entity_name:
                    raise ValueError("Существо уже не найдено. Обнови /allies.")
                if action_name == "sell_pet_inline":
                    result = sell_pet(conn, user.id, entity_name)
                elif action_name == "sell_mount_inline":
                    result = sell_mount(conn, user.id, entity_name)
                elif action_name == "offer_pet_inline":
                    trade = get_active_trade_for_player(conn, user.id)
                    if not trade:
                        raise ValueError("Сначала открой обмен: /trade @username")
                    trade = offer_trade_pet(conn, user.id, entity_name)
                    summary = _format_trade(conn, trade)
                    participant_ids = _trade_participant_telegram_ids(conn, trade)
                else:
                    trade = get_active_trade_for_player(conn, user.id)
                    if not trade:
                        raise ValueError("Сначала открой обмен: /trade @username")
                    trade = offer_trade_mount(conn, user.id, entity_name)
                    summary = _format_trade(conn, trade)
                    participant_ids = _trade_participant_telegram_ids(conn, trade)
                refreshed = get_character_for_player(conn, user.id)
            if action_name in {"offer_pet_inline", "offer_mount_inline"}:
                await query.answer("Существо добавлено в обмен.")
                if query.message:
                    pets_text = _format_named_collection("Питомцы/фамильяры", _entity_list(refreshed, "pet_json", "pets_json"))
                    companions_text = _format_named_collection("Спутники/спутницы", _entity_list(refreshed, "companion_json", "companions_json"))
                    mounts_text = _format_named_collection("Маунты", _entity_list(refreshed, "mount_json", "mounts_json"))
                    await _safe_edit_message_text(
                        query.message,
                        f"{pets_text}\n\n{companions_text}\n\n{mounts_text}",
                        reply_markup=_allies_keyboard(
                            _entity_list(refreshed, "pet_json", "pets_json"),
                            _entity_list(refreshed, "mount_json", "mounts_json"),
                        ),
                    )
                    await query.message.reply_text(f"Существо добавлено в обмен.\n\n{summary}")
                await _notify_trade_partner(
                    context,
                    participant_ids,
                    user.id,
                    f"Состав обмена обновлен.\n\n{summary}",
                )
                return

            item = result["item"]
            await query.answer("Продажа прошла.")
            if query.message:
                pets_text = _format_named_collection("Питомцы/фамильяры", _entity_list(refreshed, "pet_json", "pets_json"))
                companions_text = _format_named_collection("Спутники/спутницы", _entity_list(refreshed, "companion_json", "companions_json"))
                mounts_text = _format_named_collection("Маунты", _entity_list(refreshed, "mount_json", "mounts_json"))
                await _safe_edit_message_text(
                    query.message,
                    f"{pets_text}\n\n{companions_text}\n\n{mounts_text}",
                    reply_markup=_allies_keyboard(
                        _entity_list(refreshed, "pet_json", "pets_json"),
                        _entity_list(refreshed, "mount_json", "mounts_json"),
                    ),
                )
                label = "питомец" if entity_type == "pet" else "маунт"
                await query.message.reply_text(
                    f"Продан {label}: {item.get('name', 'без имени')} ур. {item.get('level', 1)} за {result['price']} дублонов.\n"
                    f"Теперь дублонов: {result['gold']}.",
                    reply_markup=_buyback_keyboard(int(result["listing_id"]), int(result["buyback_price"])),
                )
            return
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return

    await query.answer("Неизвестная кнопка.", show_alert=True)


def _command_body(text: str) -> str:
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _parse_numeric_command_arg(raw: str, allow_hash: bool = False) -> int | None:
    text = raw.strip()
    if not text:
        return None
    text = text.strip("<>").strip()
    lowered = text.lower()
    if lowered.startswith("id:"):
        text = text[3:].strip()
    elif lowered.startswith("id "):
        text = text[2:].strip()
    if allow_hash and text.startswith("#"):
        text = text[1:].strip()
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def _parse_item_uid_arg(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    text = text.strip("<>").strip()
    lowered = text.lower()
    if lowered.startswith("id:"):
        text = text[3:].strip()
    elif lowered.startswith("id "):
        text = text[2:].strip()
    elif lowered.startswith("id\t"):
        text = text[2:].strip()
    text = text.strip("<>").strip()
    return text


def _parse_character_payload(
    raw: str,
) -> tuple[str, str, str, str, dict[str, int], str, list[str]]:
    if "|" in raw:
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) != 7:
            raise ValueError(
                "Не понял шаблон героя.\n\n"
                "Можно по-старому:\n"
                "/create_character Имя | Пол | Раса | описание | характеристики | заклинание | предмет1, предмет2, предмет3\n\n"
                "Или по-новому, проще, в несколько строк:\n"
                "/create_character\n"
                "Имя: ...\nПол: ...\nРаса: ...\nОписание: ...\n"
                "Характеристики: сила=... ловкость=... интеллект=... харизма=... восприятие=... удача=...\n"
                "Заклинание: ...\nПредметы: предмет1, предмет2, предмет3"
            )
        name, gender, race, description = parts[:4]
        stats_raw = parts[4]
        spell = parts[5].strip()
        items_raw = parts[6]
    else:
        fields = _parse_character_fields(raw)
        missing = [label for label in ("имя", "пол", "раса", "описание", "характеристики", "заклинание", "предметы") if not fields.get(label)]
        if missing:
            raise ValueError(
                "Не хватает полей: "
                + ", ".join(missing)
                + ".\n\nПример:\n"
                "/create_character\n"
                "Имя: Хаул Ардан\n"
                "Пол: мужской\n"
                "Раса: эльф огня\n"
                "Описание: Порывистый пиромант...\n"
                "Характеристики: сила=1 ловкость=1 интеллект=10 харизма=10 восприятие=1 удача=7\n"
                "Заклинание: Огненный шар\n"
                "Предметы: перчатка, перстень, ключ"
            )
        name = fields["имя"]
        gender = fields["пол"]
        race = fields["раса"]
        description = fields["описание"]
        stats_raw = fields["характеристики"]
        spell = fields["заклинание"].strip()
        items_raw = fields["предметы"]

    if not name or not gender or not race or not description:
        raise ValueError("Имя, пол, раса и описание должны быть заполнены.")
    if len(name) > CHARACTER_NAME_MAX_LENGTH:
        raise ValueError(f"Имя героя слишком длинное: максимум {CHARACTER_NAME_MAX_LENGTH} символов.")
    if len(gender) > CHARACTER_FIELD_MAX_LENGTH:
        raise ValueError(f"Пол слишком длинный: максимум {CHARACTER_FIELD_MAX_LENGTH} символов.")
    if len(race) > CHARACTER_FIELD_MAX_LENGTH:
        raise ValueError(f"Раса слишком длинная: максимум {CHARACTER_FIELD_MAX_LENGTH} символов.")
    if len(description) < CHARACTER_DESCRIPTION_MIN_LENGTH:
        raise ValueError(
            f"Описание героя слишком короткое: хотя бы {CHARACTER_DESCRIPTION_MIN_LENGTH} символов и один внятный абзац."
        )
    if len(description) > CHARACTER_DESCRIPTION_MAX_LENGTH:
        raise ValueError(f"Описание героя слишком длинное: максимум {CHARACTER_DESCRIPTION_MAX_LENGTH} символов.")

    stats = _parse_stats(stats_raw)
    if not spell:
        raise ValueError("Укажи одно стартовое заклинание.")
    if len(spell) > ASSET_NAME_MAX_LENGTH:
        raise ValueError(f"Название заклинания слишком длинное: максимум {ASSET_NAME_MAX_LENGTH} символов.")

    items = [item.strip(" .;") for item in re.split(r"[,;\n]+", items_raw) if item.strip(" .;")]
    if len(items) != 3:
        raise ValueError("На старте нужно указать ровно 3 предмета. Можно через запятую или с новой строки после поля Предметы.")
    too_long_item = next((item for item in items if len(item) > ASSET_NAME_MAX_LENGTH), None)
    if too_long_item:
        raise ValueError(f"Название предмета слишком длинное: максимум {ASSET_NAME_MAX_LENGTH} символов.")

    return name, gender, race, description, stats, spell, items


def _parse_character_fields(raw: str) -> dict[str, str]:
    aliases = {
        "имя": "имя",
        "пол": "пол",
        "раса": "раса",
        "описание": "описание",
        "характеристики": "характеристики",
        "статы": "характеристики",
        "стат": "характеристики",
        "заклинание": "заклинание",
        "спелл": "заклинание",
        "предметы": "предметы",
        "вещи": "предметы",
        "инвентарь": "предметы",
    }
    pattern = re.compile(
        r"(?im)^\s*(имя|пол|раса|описание|характеристики|статы|стат|заклинание|спелл|предметы|вещи|инвентарь)\s*[:.\-]\s*"
    )
    matches = list(pattern.finditer(raw))
    if not matches:
        raise ValueError(
            "Не понял шаблон героя.\n\n"
            "Напиши так:\n"
            "/create_character\n"
            "Имя: ...\nПол: ...\nРаса: ...\nОписание: ...\n"
            "Характеристики: сила=... ловкость=... интеллект=... харизма=... восприятие=... удача=...\n"
            "Заклинание: ...\nПредметы: предмет1, предмет2, предмет3"
        )

    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = aliases[match.group(1).strip().lower()]
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        value = raw[start:end].strip()
        fields[key] = value
    return fields


def _parse_stats(raw: str) -> dict[str, int]:
    if not raw.strip():
        return dict(DEFAULT_STATS)

    stats: dict[str, int] = {}
    for key in STAT_NAMES:
        match = re.search(rf"(?i)\b{re.escape(key)}\b\s*(?:=|:|\s)\s*(\d+)", raw)
        if match:
            stats[key] = int(match.group(1))

    missing = [name for name in STAT_NAMES if name not in stats]
    if missing:
        raise ValueError(f"Не хватает характеристик: {', '.join(missing)}.")

    return stats


def _names_from_list(items: list[dict]) -> list[str]:
    return [str(item.get("name", "")).strip() for item in items if str(item.get("name", "")).strip()]


def _format_stats(stats: dict) -> str:
    if not stats:
        return "- нет"
    lines = []
    for name in STAT_NAMES:
        lines.append(f"- {name}: {stats.get(name, 0)}")
    return "\n".join(lines)


def _format_named_collection(title: str, items: list[dict]) -> str:
    if not items:
        return f"{title}: нет"
    lines = [f"{title}:"]
    for item in items:
        lines.append(f"- {item.get('name', 'без имени')} ур. {item.get('level', 1)}")
    return "\n".join(lines)


def _player_count_label(count: int) -> str:
    mod10 = count % 10
    mod100 = count % 100
    if mod10 == 1 and mod100 != 11:
        return "игрок"
    if mod10 in {2, 3, 4} and mod100 not in {12, 13, 14}:
        return "игрока"
    return "игроков"


def _format_public_roster(roster_rows: list[dict]) -> str:
    count = len(roster_rows)
    lines = [f"Гильдия Авентура сейчас: {count} {_player_count_label(count)}", ""]
    for row in roster_rows:
        race = str(row.get("race") or "").strip()
        race_part = f" | {race}" if race else ""
        description = " ".join(str(row.get("description") or "").split())
        lines.append(f"- {row.get('name', 'без имени')} — ур. {row.get('level', 1)}{race_part}")
        if description:
            lines.append(f"  {description}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_inventory(items: list[dict]) -> str:
    if not items:
        return "Предметы: нет"
    lines = ["Предметы:"]
    for item in items:
        uid = item.get("uid", "без-id")
        lines.append(f"- {item.get('name', 'без имени')} ур. {item.get('level', 1)} | ID: {uid}")
    lines.append("\nID можно копировать как есть или писать так: ID:abc123 / <ID:abc123>")
    return "\n".join(lines)


def _format_shop_items(items: list[dict], gold: int, can_buy_back_ids: set[int] | None = None) -> str:
    can_buy_back_ids = can_buy_back_ids or set()
    lines = [f"Лавка Каррок Манора | твои дублоны: {gold}"]
    if not items:
        lines.append("Сейчас товаров нет.")
        return "\n".join(lines)
    for item in items:
        source = "с рук" if item.get("source") == "player_sale" else "лавка"
        asset_label = _asset_type_label(item.get("asset_type", "item"))
        extra = ""
        if int(item["id"]) in can_buy_back_ids:
            extra = f" | твой товар, выкуп: {int(item.get('level', 1)) * 2}"
        lines.append(
            f"- #{item['id']} {asset_label}: {item.get('name', 'без имени')} ур. {item.get('level', 1)} "
            f"| цена: {item.get('price', 1)} | {source}{extra}"
        )
    lines.append("\nПокупка: /buy 7 или /buy <ID:7>")
    lines.append("Продажа: /sell_item abc123, /sell_pet <имя>, /sell_mount <имя>")
    return "\n".join(lines)


def _asset_type_label(asset_type: object) -> str:
    value = str(asset_type or "item")
    if value in {"item", "inventory"}:
        return "предмет"
    if value in {"spell", "spells"}:
        return "заклинание"
    if value == "pet":
        return "питомец"
    if value == "companion":
        return "спутник"
    if value == "mount":
        return "маунт"
    return "предмет"


def _shop_keyboard(items: list[dict], can_buy_back_ids: set[int] | None = None) -> InlineKeyboardMarkup:
    can_buy_back_ids = can_buy_back_ids or set()
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    (
                        f"Выкупить за {int(item.get('level', 1)) * 2}"
                        if int(item["id"]) in can_buy_back_ids
                        else f"Купить #{item['id']}"
                    ),
                    callback_data=f"buyback:{item['id']}" if int(item["id"]) in can_buy_back_ids else f"buy:{item['id']}",
                )
            ]
            for item in items
        ]
    )


def _entity_list(character: dict, legacy_column: str, list_column: str) -> list[dict]:
    entities = from_json(character.get(list_column), [])
    if entities:
        return entities
    legacy = from_json(character.get(legacy_column), None)
    return [] if legacy is None else [legacy]


def _entities_label(entities: list[dict]) -> str:
    if not entities:
        return "нет"
    return ", ".join(f"{entity.get('name', 'без имени')} ур. {entity.get('level', 1)}" for entity in entities)


def _format_statuses(statuses: object) -> str:
    if not statuses:
        return "нет"
    if isinstance(statuses, list):
        names = [str(status).strip() for status in statuses if str(status).strip()]
        return ", ".join(names) or "нет"
    if isinstance(statuses, dict):
        active = statuses.get("active")
        if isinstance(active, list):
            names = []
            for status in active:
                if isinstance(status, dict):
                    name = str(status.get("name", "")).strip()
                    note = str(status.get("note", "")).strip()
                    names.append(f"{name} ({note})" if name and note else name)
                else:
                    names.append(str(status).strip())
            return ", ".join(name for name in names if name) or "нет"
        names = []
        for key, value in statuses.items():
            if value in (False, None, "", [], {}):
                continue
            names.append(str(key))
        return ", ".join(names) or "нет"
    return str(statuses)


def _format_changes(changes: list[dict]) -> str:
    if not changes:
        return "<i>Изменения:</i> нет"

    lines = ["<i>Изменения:</i>"]
    for change in changes:
        field = change.get("field")
        if field == "level":
            delta = int(change.get("delta", 0))
            sign = "+" if delta >= 0 else ""
            lines.append(f"Уровень героя: {sign}{delta}")
        elif field == "gold":
            delta = int(change.get("delta", 0))
            sign = "+" if delta >= 0 else ""
            lines.append(f"Золото: {sign}{delta}")
        elif field == "stat":
            delta = int(change.get("delta", 0))
            sign = "+" if delta >= 0 else ""
            stat_name = html.escape(str(change.get("stat") or change.get("name") or "характеристика"))
            lines.append(f"{stat_name}: {sign}{delta}")
        elif field == "inventory":
            item = change.get("item") or change.get("value") or {}
            lines.append(f"Предмет: {html.escape(_reward_name(item))}")
        elif field == "spells":
            spell = change.get("spell") or change.get("value") or {}
            lines.append(f"Заклинание: {html.escape(_reward_name(spell))}")
        elif field == "pet":
            pet = change.get("pet") or change.get("value") or {}
            lines.append(f"Питомец: {html.escape(_reward_name(pet))}")
        elif field == "familiar":
            familiar = change.get("familiar") or change.get("pet") or change.get("value") or {}
            lines.append(f"Фамильяр: {html.escape(_reward_name(familiar))}")
        elif field == "companion":
            companion = change.get("companion") or change.get("value") or {}
            lines.append(f"Спутник/спутница: {html.escape(_reward_name(companion))}")
        elif field == "mount":
            mount = change.get("mount") or change.get("value") or {}
            lines.append(f"Маунт: {html.escape(_reward_name(mount))}")
        elif field == "status":
            action = change.get("action") or "set"
            if action == "remove":
                lines.append(f"Состояние снято: {html.escape(_status_name(change))}")
            else:
                lines.append(f"Состояние: {html.escape(_status_name(change))}")
        else:
            lines.append(html.escape(str(change)))
    return "\n".join(lines)


def _is_boss_trophy_change(change: dict) -> bool:
    return str(change.get("source") or "").strip() == "boss_trophy"


def _split_boss_trophy_changes(changes: list[dict]) -> tuple[list[dict], list[dict]]:
    boss_trophies: list[dict] = []
    other_changes: list[dict] = []
    for change in changes:
        if _is_boss_trophy_change(change):
            boss_trophies.append(change)
        else:
            other_changes.append(change)
    return boss_trophies, other_changes


def _boss_trophy_label(change: dict) -> str:
    field = str(change.get("field") or "")
    if field == "inventory":
        return f"Артефакт: {html.escape(_reward_name(change.get('item') or change.get('value') or {}))}"
    if field == "spells":
        return f"Формула: {html.escape(_reward_name(change.get('spell') or change.get('value') or {}))}"
    if field == "pet":
        return f"Питомец: {html.escape(_reward_name(change.get('pet') or change.get('value') or {}))}"
    if field == "companion":
        return f"Спутник: {html.escape(_reward_name(change.get('companion') or change.get('value') or {}))}"
    if field == "mount":
        return f"Маунт: {html.escape(_reward_name(change.get('mount') or change.get('value') or {}))}"
    return f"Трофей: {html.escape(str(change))}"


def _format_boss_trophy_block(changes: list[dict]) -> str:
    if not changes:
        return ""
    lines = ["<b>Трофей босса:</b>"]
    for change in changes:
        lines.append(_boss_trophy_label(change))
        reason = str(change.get("reason") or "").strip()
        if reason:
            lines.append(f"<i>{html.escape(reason)}</i>")
    return "\n".join(lines)


def _status_name(change: dict) -> str:
    value = change.get("status") or change.get("value") or change.get("name") or "без названия"
    if isinstance(value, dict):
        name = value.get("name", "без названия")
        note = value.get("note")
        return f"{name} ({note})" if note else str(name)
    return str(value)


def _reward_name(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name", "без имени")
        level = value.get("level", 1)
        return f"{name} ур. {level}"
    return "без имени"


def _format_change_log(changes: list[dict]) -> str:
    lines = ["Последние изменения:"]
    for change in changes:
        reason = change.get("reason") or "без причины"
        turn_title = change.get("turn_title") or f"Ход {change.get('turn_id')}"
        lines.append(f"- {change['created_at']} | {turn_title} | {change['field']}: {reason}")
    return "\n".join(lines)


def _format_chronicle_entries(entries: list[dict]) -> str:
    lines = ["Последние записи хроники:"]
    for entry in entries:
        lines.append(f"- Ход #{entry['turn_id']} | {entry['mission_title']} | {entry['status']}: {entry['public_summary']}")
        world_changes = from_json(entry.get("world_changes_json"), [])
        if not isinstance(world_changes, list):
            world_changes = [str(world_changes)]
        for change in world_changes:
            lines.append(f"  • {change}")
    return "\n".join(lines)


def _format_trade(conn, trade: dict) -> str:
    initiator = _character_with_player_by_id(conn, int(trade["initiator_character_id"]))
    target = _character_with_player_by_id(conn, int(trade["target_character_id"]))
    if not initiator or not target:
        return "Обмен: участник не найден."

    all_items = [
        *from_json(initiator["inventory_json"], []),
        *from_json(target["inventory_json"], []),
    ]
    all_pets = [
        *_entity_list(initiator, "pet_json", "pets_json"),
        *_entity_list(target, "pet_json", "pets_json"),
    ]
    all_mounts = [
        *_entity_list(initiator, "mount_json", "mounts_json"),
        *_entity_list(target, "mount_json", "mounts_json"),
    ]
    initiator_items = _trade_items_label(all_items, from_json(trade["initiator_items_json"], []))
    target_items = _trade_items_label(all_items, from_json(trade["target_items_json"], []))
    initiator_pets = _trade_named_entities_label(all_pets, from_json(trade["initiator_pets_json"], []))
    target_pets = _trade_named_entities_label(all_pets, from_json(trade["target_pets_json"], []))
    initiator_mounts = _trade_named_entities_label(all_mounts, from_json(trade["initiator_mounts_json"], []))
    target_mounts = _trade_named_entities_label(all_mounts, from_json(trade["target_mounts_json"], []))
    initiator_confirmed = "да" if int(trade["initiator_confirmed"]) else "нет"
    target_confirmed = "да" if int(trade["target_confirmed"]) else "нет"
    return (
        f"Обмен #{trade['id']} | {trade['status']}\n"
        f"{initiator['name']} отдает: предметы {initiator_items}; питомцы {initiator_pets}; маунты {initiator_mounts}; дублоны: {trade['initiator_gold']} | подтверждено: {initiator_confirmed}\n"
        f"{target['name']} отдает: предметы {target_items}; питомцы {target_pets}; маунты {target_mounts}; дублоны: {trade['target_gold']} | подтверждено: {target_confirmed}\n\n"
        "Команды: /offer_item abc123, /offer_pet <имя>, /offer_mount <имя>, /remove_item abc123, /remove_pet <имя>, /remove_mount <имя>, /offer_gold <число>, /accept_trade, /cancel_trade"
    )


def _trade_items_label(all_items: list[dict], item_uids: list[str]) -> str:
    if not item_uids:
        return "ничего"
    by_uid = {str(item.get("uid")): item for item in all_items if isinstance(item, dict)}
    labels = []
    for uid in item_uids:
        item = by_uid.get(str(uid))
        if item:
            labels.append(f"{item.get('name', 'без имени')} ур. {item.get('level', 1)}")
        else:
            labels.append(f"предмет {uid}")
    return ", ".join(labels)


def _trade_named_entities_label(all_entities: list[dict], names: list[str]) -> str:
    if not names:
        return "ничего"
    by_name = {str(entity.get("name", "")).casefold(): entity for entity in all_entities if isinstance(entity, dict)}
    labels = []
    for name in names:
        entity = by_name.get(str(name).casefold())
        if entity:
            labels.append(f"{entity.get('name', 'без имени')} ур. {entity.get('level', 1)}")
        else:
            labels.append(str(name))
    return ", ".join(labels)


def _character_with_player_by_id(conn, character_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT characters.*, players.telegram_id, players.username, players.notify_enabled
        FROM characters
        JOIN players ON players.id = characters.player_id
        WHERE characters.id = ?
        """,
        (character_id,),
    ).fetchone()
    return None if row is None else dict(row)


def _trade_participant_telegram_ids(conn, trade: dict) -> list[int]:
    ids = []
    for key in ("initiator_character_id", "target_character_id"):
        character = _character_with_player_by_id(conn, int(trade[key]))
        if character and int(character.get("notify_enabled", 1)) == 1:
            ids.append(int(character["telegram_id"]))
    return ids


async def _notify_trade_partner(
    context: ContextTypes.DEFAULT_TYPE,
    participant_ids: list[int],
    sender_id: int,
    text: str,
) -> None:
    for chat_id in participant_ids:
        if int(chat_id) == int(sender_id):
            continue
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            continue


def _prepare_generation_workbench(settings: Settings, seed_path: Path) -> Path:
    workbench_path = settings.workbench_dir / f"generation_{seed_path.stem.removeprefix('turn_seed_')}"
    workbench_path.mkdir(parents=True, exist_ok=True)
    shutil.copy2(seed_path, workbench_path / "turn_seed.yaml")
    _copy_if_exists(Path("prompts/mission_generation_instructions.md"), workbench_path / "mission_generation_instructions.md")
    _copy_tree_if_exists(Path("lore"), workbench_path / "lore")
    _copy_if_exists(settings.chronicle_dir / "chronicle.md", workbench_path / "chronicle.md")
    (workbench_path / "task.md").write_text(
        "Сгенерируй turn.yaml по turn_seed.yaml, папке lore/, chronicle.md и текущей базе персонажей.\n"
        "Сохрани результат как turn.yaml в этой папке.\n",
        encoding="utf-8",
    )
    return workbench_path


def _pending_turn_art_path(settings: Settings) -> Path:
    return settings.art_dir / "pending_turn_art.json"


def _load_pending_turn_art(settings: Settings) -> dict | None:
    path = _pending_turn_art_path(settings)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload if isinstance(payload, dict) else None


def _turn_art_payload(payload: dict) -> dict:
    turn = payload.get("turn", {})
    art = turn.get("art") if isinstance(turn.get("art"), dict) else {}
    return art


def _turn_art_prompt(payload: dict) -> str:
    turn = payload.get("turn", {})
    art = _turn_art_payload(payload)
    return str(art.get("prompt") or turn.get("art_prompt") or "").strip()


def _turn_art_caption(payload: dict) -> str:
    turn = payload.get("turn", {})
    art = _turn_art_payload(payload)
    return str(art.get("caption") or turn.get("art_caption") or "").strip()


def _turn_art_file_id(payload: dict) -> str:
    art = _turn_art_payload(payload)
    return str(art.get("telegram_file_id") or art.get("file_id") or "").strip()


def _prepare_resolution_workbench(settings: Settings, turn_id: int, export_path: Path) -> Path:
    workbench_path = settings.workbench_dir / f"turn_{turn_id}"
    workbench_path.mkdir(parents=True, exist_ok=True)
    shutil.copy2(export_path, workbench_path / "export.json")
    _copy_if_exists(Path("prompts/gm_instructions.md"), workbench_path / "gm_instructions.md")
    _copy_if_exists(Path("resolution_notes/resolution_notes.sample.yaml"), workbench_path / "resolution_notes.template.yaml")
    (workbench_path / "task.md").write_text(
        f"Обработай export.json для хода #{turn_id}.\n"
        "Если есть resolution_notes.yaml, учти их с высшим приоритетом.\n"
        "Сохрани результат как result.json, затем положи копию в data/imports/pending/.\n",
        encoding="utf-8",
    )
    return workbench_path


def _copy_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copy2(source, destination)


def _copy_tree_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        shutil.copytree(source, destination, dirs_exist_ok=True)


def _backup_database(settings: Settings) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = settings.backups_dir / f"aventura_{timestamp}.sqlite"
    shutil.copy2(settings.database_path, backup_path)
    return backup_path


async def _close_and_export_turn(
    application: Application,
    settings: Settings,
    turn_id: int,
    notify_admins: bool = True,
) -> Path:
    with connect(settings.database_path) as conn:
        turn = get_open_turn(conn)
        if not turn or int(turn["id"]) != int(turn_id):
            raise ValueError(f"Ход #{turn_id} уже закрыт или не является текущим открытым ходом.")
        close_turn(conn, turn_id)
        payload = build_turn_export(conn, turn_id)

    export_path = settings.exports_dir / f"turn_{turn_id}_export.json"
    write_json(export_path, payload)
    with connect(settings.database_path) as conn:
        mark_exported(conn, turn_id, export_path)

    workbench_path = _prepare_resolution_workbench(settings, turn_id, export_path)
    if notify_admins:
        for admin_id in settings.admin_telegram_ids:
            await application.bot.send_document(
                chat_id=admin_id,
                document=export_path,
                caption=f"Ход #{turn_id} закрыт по дедлайну. Workbench: {workbench_path}",
            )
    return export_path


async def _import_and_publish_result(
    application: Application,
    settings: Settings,
    result_path: Path,
    publish: bool,
) -> dict:
    payload = load_result_json(result_path)
    saved_path = settings.imports_dir / f"turn_{payload['turn_id']}_result.json"
    write_json(saved_path, payload)
    _backup_database(settings)
    snapshot_error: str | None = None
    with connect(settings.database_path) as conn:
        apply_result_payload(conn, payload)
        _write_chronicle_files(settings, list_city_chronicle(conn, limit=500))
        snapshot_payload = build_heroes_snapshot(conn, turn_id=int(payload["turn_id"]))
    try:
        _write_heroes_snapshot_files(settings, int(payload["turn_id"]), snapshot_payload)
    except Exception as exc:
        snapshot_error = str(exc)
    if publish:
        await _publish_results_for_turn(application, int(payload["turn_id"]))
    if snapshot_error:
        for admin_id in settings.admin_telegram_ids:
            try:
                await application.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"Результат хода #{payload['turn_id']} импортирован, "
                        f"но heroes snapshot не удалось сохранить: {snapshot_error}"
                    ),
                )
            except Exception:
                continue
    return payload


def _write_chronicle_files(settings: Settings, entries: list[dict]) -> None:
    serializable_entries = []
    for entry in entries:
        serializable_entries.append(
            {
                "turn_id": entry["turn_id"],
                "mission_id": entry["mission_id"],
                "turn_title": entry["turn_title"],
                "mission_title": entry["mission_title"],
                "status": entry["status"],
                "public_summary": entry["public_summary"],
                "world_changes": from_json(entry.get("world_changes_json"), []),
                "created_at": entry["created_at"],
            }
        )
    write_json(settings.chronicle_dir / "chronicle.json", {"entries": serializable_entries})
    (settings.chronicle_dir / "chronicle.md").write_text(
        _format_chronicle_markdown(serializable_entries),
        encoding="utf-8",
    )


def _write_heroes_snapshot_files(settings: Settings, turn_id: int, payload: dict) -> None:
    snapshot_by_turn = settings.exports_dir / f"heroes_snapshot_turn_{turn_id}.json"
    latest_snapshot = settings.chronicle_dir / "heroes_snapshot_latest.json"
    write_json(snapshot_by_turn, payload)
    write_json(latest_snapshot, payload)


def _format_chronicle_markdown(entries: list[dict]) -> str:
    lines = [
        "# Хроника Танелорна",
        "",
        "Краткая память города по уже сыгранным миссиям. Используй ее при генерации новых ходов, чтобы учитывать последствия и не противоречить прошлым событиям.",
        "",
    ]
    if not entries:
        lines.append("Хроника пока пуста.")
        lines.append("")
        return "\n".join(lines)

    current_turn_id = None
    for entry in entries:
        if entry["turn_id"] != current_turn_id:
            current_turn_id = entry["turn_id"]
            lines.extend(["", f"## Ход #{entry['turn_id']}: {entry['turn_title']}", ""])
        lines.append(f"### {entry['mission_title']} ({entry['status']})")
        lines.append("")
        lines.append(entry["public_summary"])
        world_changes = entry.get("world_changes") or []
        if world_changes:
            lines.append("")
            lines.append("Последствия:")
            for change in world_changes:
                lines.append(f"- {change}")
        lines.append("")
    return "\n".join(lines)


async def _publish_results_for_turn(application: Application, turn_id: int) -> tuple[int, int]:
    public_count = 0
    personal_count = 0
    settings = application.bot_data["settings"]
    with connect(settings.database_path) as conn:
        publications = pending_publications(conn, turn_id)
        player_chat_ids = list_player_telegram_ids(conn)
        group_chat_id = settings.game_chat_id
        for publication in publications:
            result = from_json(publication["result_json"], {})
            public_overview = html.escape(
                result.get("public_overview")
                or result.get("public_summary")
                or "Итог миссии пока не записан."
            )
            public_text = (
                f"<b>Общий итог миссии: {html.escape(publication['mission_title'])}</b>\n\n"
                f"{public_overview}"
            )
            if group_chat_id is not None:
                try:
                    await application.bot.send_message(chat_id=group_chat_id, text=public_text, parse_mode=ParseMode.HTML)
                except Exception:
                    pass
            for chat_id in player_chat_ids:
                try:
                    await application.bot.send_message(chat_id=chat_id, text=public_text, parse_mode=ParseMode.HTML)
                except Exception:
                    continue
            public_count += 1

            for player_result in result.get("player_results", []):
                telegram_id = character_telegram_id(conn, int(player_result["character_id"]))
                if telegram_id is None:
                    continue
                boss_trophies, other_changes = _split_boss_trophy_changes(player_result.get("changes", []))
                changes_text = _format_changes(other_changes)
                boss_trophy_block = _format_boss_trophy_block(boss_trophies)
                parts = [
                    f"<b>Личный результат: {html.escape(publication['mission_title'])}</b>",
                    html.escape(player_result.get("message", "")),
                ]
                if boss_trophy_block:
                    parts.append(boss_trophy_block)
                parts.append(changes_text)
                text = "\n\n".join(parts)
                await application.bot.send_message(chat_id=telegram_id, text=text, parse_mode=ParseMode.HTML)
                personal_count += 1
            mark_result_published(conn, publication["id"])
        for craft_publication in pending_craft_publications(conn, turn_id):
            result = from_json(craft_publication["result_json"], {})
            telegram_id = int(craft_publication["telegram_id"])
            text = _format_craft_publication(result)
            try:
                await application.bot.send_message(chat_id=telegram_id, text=text, parse_mode=ParseMode.HTML)
                personal_count += 1
            except Exception:
                continue
            mark_craft_published(conn, int(craft_publication["id"]))
    return public_count, personal_count


def _format_craft_publication(result: dict) -> str:
    base = result.get("base") if isinstance(result.get("base"), dict) else {}
    material = result.get("material") if isinstance(result.get("material"), dict) else {}
    crafted = result.get("result") if isinstance(result.get("result"), dict) else {}
    message = str(result.get("message") or "").strip()
    lines = [
        "<b>Результат крафта</b>",
        "",
        "Из слияния:",
        f"{html.escape(str(base.get('name') or 'основа'))} + {html.escape(str(material.get('name') or 'материал'))}",
        "",
        "Получилось:",
        f"{html.escape(str(crafted.get('name') or 'новый актив'))}, {_asset_type_label(crafted.get('type'))} ур. {html.escape(str(crafted.get('level', 1)))}",
    ]
    description = str(crafted.get("description") or "").strip()
    if description:
        lines.extend(["", html.escape(description)])
    if message:
        lines.extend(["", html.escape(message)])
    return "\n".join(lines)


def _parse_deadline(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


async def _deadline_monitor(application: Application) -> None:
    settings = application.bot_data["settings"]
    while True:
        try:
            with connect(settings.database_path) as conn:
                turn = get_open_turn(conn)
            if turn:
                deadline = _parse_deadline(turn.get("deadline"))
                if deadline and datetime.now() >= deadline:
                    await _close_and_export_turn(application, settings, int(turn["id"]), notify_admins=True)
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _notify_admins(application, f"Ошибка автозакрытия хода: {exc}")
            await asyncio.sleep(60)


async def _pending_import_monitor(application: Application) -> None:
    settings = application.bot_data["settings"]
    while True:
        try:
            for result_path in sorted(settings.pending_imports_dir.glob("*.json")):
                if datetime.now() - datetime.fromtimestamp(result_path.stat().st_mtime) < timedelta(seconds=2):
                    continue
                try:
                    payload = await _import_and_publish_result(application, settings, result_path, publish=True)
                    target = settings.processed_imports_dir / result_path.name
                    shutil.move(str(result_path), target)
                    await _notify_admins(application, f"Pending result импортирован и опубликован: ход #{payload['turn_id']}.")
                except Exception as exc:
                    target = settings.failed_imports_dir / result_path.name
                    shutil.move(str(result_path), target)
                    await _notify_admins(application, f"Pending result не принят ({result_path.name}): {exc}")
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _notify_admins(application, f"Ошибка pending-import watcher: {exc}")
            await asyncio.sleep(30)


async def _notify_admins(application: Application, text: str) -> None:
    settings = application.bot_data["settings"]
    for admin_id in settings.admin_telegram_ids:
        try:
            await application.bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            continue


async def _post_init(application: Application) -> None:
    application.bot_data["background_tasks"] = [
        asyncio.create_task(_deadline_monitor(application)),
        asyncio.create_task(_pending_import_monitor(application)),
    ]


async def _post_shutdown(application: Application) -> None:
    for task in application.bot_data.get("background_tasks", []):
        task.cancel()


def build_application(settings: Settings) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).post_init(_post_init).post_shutdown(_post_shutdown).build()
    app.bot_data["settings"] = settings

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("list", help_cmd))
    app.add_handler(CommandHandler("create_character", create_character_cmd))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("roster", roster))
    app.add_handler(CommandHandler("players", roster))
    app.add_handler(CommandHandler("sheet", sheet))
    app.add_handler(CommandHandler("inventory", inventory))
    app.add_handler(CommandHandler("spells", spells))
    app.add_handler(CommandHandler("allies", allies))
    app.add_handler(CommandHandler("log", log_cmd))
    app.add_handler(CommandHandler("export_sheet", export_sheet))
    app.add_handler(CommandHandler("chat_id", chat_id_cmd))
    app.add_handler(CommandHandler("missions", missions))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("action", action))
    app.add_handler(CommandHandler("my_action", my_action))
    app.add_handler(CommandHandler("craft", craft_cmd))
    app.add_handler(CommandHandler("shop", shop_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("sell_item", sell_item_cmd))
    app.add_handler(CommandHandler("sell_pet", sell_pet_cmd))
    app.add_handler(CommandHandler("sell_mount", sell_mount_cmd))
    app.add_handler(CommandHandler("trade", trade_cmd))
    app.add_handler(CommandHandler("offer_item", offer_item_cmd))
    app.add_handler(CommandHandler("offer_pet", offer_pet_cmd))
    app.add_handler(CommandHandler("offer_mount", offer_mount_cmd))
    app.add_handler(CommandHandler("remove_item", remove_item_cmd))
    app.add_handler(CommandHandler("remove_pet", remove_pet_cmd))
    app.add_handler(CommandHandler("remove_mount", remove_mount_cmd))
    app.add_handler(CommandHandler("offer_gold", offer_gold_cmd))
    app.add_handler(CommandHandler("trade_status", trade_status_cmd))
    app.add_handler(CommandHandler("accept_trade", accept_trade_cmd))
    app.add_handler(CommandHandler("cancel_trade", cancel_trade_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("refresh_shop", refresh_shop_cmd))
    app.add_handler(CommandHandler("export_turn", export_turn))
    app.add_handler(CommandHandler("publish_results", publish_results))
    app.add_handler(CommandHandler("chronicle", chronicle_cmd))
    app.add_handler(
        CallbackQueryHandler(
            inline_action_handler,
            pattern=(
                r"^(join|buy|buyback|action_template|sell_pet_inline|offer_pet_inline|sell_mount_inline|offer_mount_inline):\d+$"
                r"|^(sell_item|offer_item_inline):[A-Za-z0-9_-]+$"
                r"|^craft_(base|material):[A-Za-z0-9_:-]+$"
                r"|^craft_(confirm|cancel)$"
            ),
        )
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text_handler))
    app.add_handler(MessageHandler((filters.PHOTO | filters.Document.IMAGE) & filters.CaptionRegex(r"^/turn_art\b"), handle_turn_art_upload))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    return app


def main() -> None:
    settings = load_settings()
    with connect(settings.database_path) as conn:
        init_db(conn)
    app = build_application(settings)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
