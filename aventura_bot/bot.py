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
from aventura_bot.db import connect, from_json, init_db
from aventura_bot.services.game import (
    ACTION_TEXT_MAX_LENGTH,
    ACTION_TEXT_MIN_LENGTH,
    ASSET_NAME_MAX_LENGTH,
    CHARACTER_DESCRIPTION_MAX_LENGTH,
    CHARACTER_DESCRIPTION_MIN_LENGTH,
    CHARACTER_FIELD_MAX_LENGTH,
    CHARACTER_NAME_MAX_LENGTH,
    DEFAULT_STATS,
    STAT_NAMES,
    apply_result_payload,
    build_turn_export,
    character_telegram_id,
    close_turn,
    create_character,
    create_turn_from_payload,
    get_character_change_log,
    mission_difficulty_bounds,
    get_character_for_player,
    get_open_turn,
    list_city_chronicle,
    join_mission,
    list_player_telegram_ids,
    list_open_missions,
    mark_exported,
    mark_result_published,
    pending_publications,
    recommended_mission_count,
    submit_action,
    set_turn_art,
    accept_trade,
    cancel_trade,
    get_active_trade_for_player,
    buy_back_shop_item,
    buy_shop_item,
    offer_trade_gold,
    offer_trade_item,
    offer_trade_mount,
    offer_trade_pet,
    list_shop_items,
    player_can_buy_back,
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
from aventura_bot.services.turn_files import (
    is_seed_payload,
    is_turn_payload,
    load_character_restore_json,
    load_result_json,
    load_turn_yaml,
    load_yaml,
    validate_seed_payload,
    validate_turn_payload,
    write_json,
)


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _is_admin(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    return bool(user and user.id in settings.admin_telegram_ids)


async def _require_private_chat(update: Update) -> bool:
    if update.effective_chat and update.effective_chat.type == "private":
        return True
    if update.message:
        await update.message.reply_text("Эту команду лучше отправить мне в личные сообщения.")
    return False


async def _safe_edit_message_text(message, text: str, reply_markup=None) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
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
MENU_PROFILE = "Профиль"
MENU_COMMANDS = "Команды"


def _main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(MENU_MISSIONS), KeyboardButton(MENU_MY_ACTION)],
            [KeyboardButton(MENU_HERO), KeyboardButton(MENU_SHOP)],
            [KeyboardButton(MENU_PROFILE), KeyboardButton(MENU_COMMANDS)],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.message:
        return
    if not await _require_private_chat(update):
        return
    with _db(context) as conn:
        upsert_player(conn, update.effective_user.id, update.effective_user.username)
        character = get_character_for_player(conn, update.effective_user.id)

    if character:
        await update.message.reply_text(
            f"Ты уже в гильдии Авентура: {character['name']}, {character['race']}.",
            reply_markup=_main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            "Добро пожаловать в Авентуру. Создай персонажа командой:\n"
            "/create_character Имя | Пол | Раса | описание | характеристики | заклинание | предмет1, предмет2, предмет3\n\n"
            "Питомца, спутника и маунта на старте нет.",
            reply_markup=_main_menu_keyboard(),
        )


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
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return

    await update.message.reply_text(
        f"Персонаж создан: {character['name']}, {character['gender']}, {character['race']}.\n"
        f"Описание: {description}\n"
        f"Стартовое заклинание: {spell} ур. 1.\n"
        f"Предметы ур. 1: {', '.join(items)}."
    )


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
    await update.message.reply_text(f"{pets}\n\n{companions}\n\n{mounts}")


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
        f"Уровень: {character['level']} | XP: {character['xp']} | Золото: {character['gold']}\n"
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

    await update.message.reply_text(_format_missions(mission_list), reply_markup=_missions_keyboard(mission_list))


def _format_missions(mission_list: list[dict]) -> str:
    lines = [
        "Открытые миссии:",
        f"Ответ свободный, главное чтобы было понятно, что делает герой. По длине ориентир: {ACTION_TEXT_MIN_LENGTH}-{ACTION_TEXT_MAX_LENGTH} символов.",
    ]
    for mission in mission_list:
        lines.append(
            f"\n#{mission['id']} — {mission['title']}\n"
            f"Сложность: {mission['difficulty']}\n"
            f"{mission['description']}\n"
            f"Выбор: /join {mission['id']}"
        )
    return "\n".join(lines)


def _missions_keyboard(mission_list: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"Вступить в #{mission['id']}", callback_data=f"join:{mission['id']}")]
        for mission in mission_list
    ]
    return InlineKeyboardMarkup(rows)


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
        rows.append([InlineKeyboardButton(f"Продать за {sell_price}: {short_name}", callback_data=f"sell_item:{uid}")])
    return InlineKeyboardMarkup(rows) if rows else None


def _buyback_keyboard(listing_id: int, price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"Выкупить обратно за {price}", callback_data=f"buyback:{listing_id}")]]
    )


def _action_template_keyboard(mission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Написать действие", callback_data=f"action_template:{mission_id}")]]
    )


def _action_template_text(mission_title: str) -> str:
    return (
        f"Шаблон для миссии «{mission_title}»:\n\n"
        "/action Сначала мой герой оценивает обстановку и понимает, в чем главный конфликт этой миссии. "
        "Он выбирает понятный способ вмешаться и использует те сильные стороны, которые подходят именно к этой ситуации.\n\n"
        "Потом герой предпринимает основное действие: атакует, договаривается, исследует, защищает или обманывает - в зависимости от задачи. "
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
    await update.message.reply_text(
        f"Ты записан на миссию: {mission['title']}.\n"
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
            f"Формат: /action текст. Опиши, как герой пытается решить конфликт миссии. "
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
        await update.message.reply_text(
            f"Ход #{row['turn_id']}: {row['turn_title']}\n"
            f"Дедлайн: {row['deadline'] or 'не указан'}\n"
            f"Миссия #{row['mission_id']}: {row['mission_title']}\n\n"
            "Действие еще не отправлено. Формат: /action текст"
        )
        return

    await update.message.reply_text(
        f"Ход #{row['turn_id']}: {row['turn_title']}\n"
        f"Дедлайн: {row['deadline'] or 'не указан'}\n"
        f"Миссия #{row['mission_id']}: {row['mission_title']}\n"
        f"Отправлено: {row['submitted_at'] or 'время не записано'}\n\n"
        f"Твой текущий ход:\n{action_text}\n\n"
        "Можно заменить до дедлайна новой командой /action."
    )


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
    if is_seed_payload(payload):
        validate_seed_payload(payload)
        await _handle_seed_yaml(update, context, local_path, payload)
        return
    raise ValueError("Не понял YAML: нужен turn.yaml с missions или turn_seed.yaml с theme/generation/mission_seeds.")


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

    mission_text = _format_missions(mission_list)
    for chat_id in player_chat_ids:
        try:
            if art_file_id:
                await context.bot.send_photo(chat_id=chat_id, photo=art_file_id, caption=art_caption[:1024])
            await context.bot.send_message(chat_id=chat_id, text=mission_text)
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
        "/create_character Имя | Пол | Раса | описание | характеристики | заклинание | предмет1, предмет2, предмет3\n"
        "/profile\n"
        "/sheet\n"
        "/inventory\n"
        "/spells\n"
        "/allies\n"
        "/log\n"
        "/missions\n"
        "/join <id>\n"
        "/action <текст>\n"
        "/my_action\n"
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
        "/export_turn\n"
        "загрузить result.json\n"
        "/publish_results <turn_id>\n"
        "/chronicle\n\n"
        "Нижние кнопки помогают не помнить команды наизусть: "
        "Миссии, Мой ход, Герой, Лавка, Профиль, Команды.\n"
        "Для действий с параметрами можно писать свободнее, например: /join #3, /buy <ID:7>, /sell_item ID:abc123 или /offer_pet Имя.",
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
    if text == MENU_PROFILE:
        await profile(update, context)
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
                mission_list = list_open_missions(conn)
            await query.answer("Ты записан на миссию.")
            if query.message:
                await _safe_edit_message_text(query.message, _format_missions(mission_list), reply_markup=_missions_keyboard(mission_list))
                await query.message.reply_text(
                    f"Ты записан на миссию: {mission['title']}.\n"
                    "Теперь отправь действие: /action текст\n"
                    f"Пиши свободно, главное чтобы было понятно, что делает герой. По длине ориентир: {ACTION_TEXT_MIN_LENGTH}-{ACTION_TEXT_MAX_LENGTH} символов.",
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
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 7:
        raise ValueError(
            "Формат: /create_character Имя | Пол | Раса | описание в 1 абзац | "
            "сила=5 ловкость=5 интеллект=5 харизма=5 восприятие=5 удача=5 | "
            "заклинание | предмет1, предмет2, предмет3"
        )

    name, gender, race, description = parts[:4]
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

    stats = _parse_stats(parts[4])
    spell = parts[5].strip()
    if not spell:
        raise ValueError("Укажи одно стартовое заклинание.")
    if len(spell) > ASSET_NAME_MAX_LENGTH:
        raise ValueError(f"Название заклинания слишком длинное: максимум {ASSET_NAME_MAX_LENGTH} символов.")

    items = [item.strip() for item in parts[6].split(",") if item.strip()]
    if len(items) != 3:
        raise ValueError("На старте нужно указать ровно 3 предмета через запятую.")
    too_long_item = next((item for item in items if len(item) > ASSET_NAME_MAX_LENGTH), None)
    if too_long_item:
        raise ValueError(f"Название предмета слишком длинное: максимум {ASSET_NAME_MAX_LENGTH} символов.")

    return name, gender, race, description, stats, spell, items


def _parse_stats(raw: str) -> dict[str, int]:
    if not raw.strip():
        return dict(DEFAULT_STATS)

    stats: dict[str, int] = {}
    for token in raw.replace(",", " ").split():
        if "=" not in token:
            raise ValueError(f"Не понял характеристику '{token}'. Используй формат сила=5.")
        key, value = [chunk.strip().lower() for chunk in token.split("=", 1)]
        if key not in STAT_NAMES:
            raise ValueError(f"Неизвестная характеристика '{key}'. Нужно: {', '.join(STAT_NAMES)}.")
        if not value.isdigit():
            raise ValueError(f"Значение характеристики '{key}' должно быть целым числом.")
        stats[key] = int(value)

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
    if value == "pet":
        return "питомец"
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
        lines.append(
            f"- Ход #{entry['turn_id']} | {entry['mission_title']} | {entry['status']}: "
            f"{entry['public_summary']}"
        )
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
        SELECT characters.*, players.telegram_id, players.username
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
        if character:
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
    with connect(settings.database_path) as conn:
        apply_result_payload(conn, payload)
        _write_chronicle_files(settings, list_city_chronicle(conn, limit=500))
    if publish:
        await _publish_results_for_turn(application, int(payload["turn_id"]))
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
        for publication in publications:
            result = from_json(publication["result_json"], {})
            public_summary = html.escape(result.get("public_summary") or "Итог миссии пока не записан.")
            public_text = (
                f"<b>Общий итог миссии: {html.escape(publication['mission_title'])}</b>\n\n"
                f"{public_summary}"
            )
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
                changes_text = _format_changes(player_result.get("changes", []))
                text = (
                    f"<b>Личный результат: {html.escape(publication['mission_title'])}</b>\n\n"
                    f"{html.escape(player_result.get('message', ''))}\n\n"
                    f"{changes_text}"
                )
                await application.bot.send_message(chat_id=telegram_id, text=text, parse_mode=ParseMode.HTML)
                personal_count += 1
            mark_result_published(conn, publication["id"])
    return public_count, personal_count


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
    app.add_handler(CommandHandler("sheet", sheet))
    app.add_handler(CommandHandler("inventory", inventory))
    app.add_handler(CommandHandler("spells", spells))
    app.add_handler(CommandHandler("allies", allies))
    app.add_handler(CommandHandler("log", log_cmd))
    app.add_handler(CommandHandler("export_sheet", export_sheet))
    app.add_handler(CommandHandler("missions", missions))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("action", action))
    app.add_handler(CommandHandler("my_action", my_action))
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
    app.add_handler(CommandHandler("export_turn", export_turn))
    app.add_handler(CommandHandler("publish_results", publish_results))
    app.add_handler(CommandHandler("chronicle", chronicle_cmd))
    app.add_handler(CallbackQueryHandler(inline_action_handler, pattern=r"^(join|buy|buyback|action_template):\d+$|^sell_item:[A-Za-z0-9_-]+$"))
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
