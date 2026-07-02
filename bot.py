"""Duck Hunt Telegram Bot."""

from __future__ import annotations

import html
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from db import DuckDatabase
from gemini import verify_duck_photo
import spots
from state import BotState

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "").strip()
GROUP_TOPIC_ID = os.getenv("GROUP_TOPIC_ID", "").strip()
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()
TOTAL_DUCKS = int(os.getenv("TOTAL_DUCKS", "100"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
DB_PATH = os.getenv("DB_PATH", "ducks.db")
DUCK_SPOTS_DIR = Path(os.getenv("DUCK_SPOTS_DIR", "duck_spots"))
STATE_PATH = Path(os.getenv("STATE_PATH", "bot_state.json"))

db = DuckDatabase(DB_PATH)
state = BotState(STATE_PATH)

PARSE_MODE = "HTML"
REVIEW_STREAK_THRESHOLD = 2

PLAYER_COMMANDS: list[tuple[str, str]] = [
    ("start", "Rules and how to claim"),
    ("help", "List available commands"),
    ("leaderboard", "See who's found the most ducks"),
    ("remaining", "See how many ducks are left"),
]

ADMIN_COMMANDS: list[tuple[str, str]] = [
    ("input_mode", "Start saving hiding-spot photos"),
    ("done", "Exit input mode"),
    ("spot", "Retrieve hiding photo for a duck number"),
    ("missing", "List duck numbers without a saved spot"),
    ("start_game", "Open the hunt for new claims"),
    ("end_game", "Stop accepting new claims"),
    ("remove", "Revoke a duck claim"),
    ("chatid", "Print chat/topic IDs for setup"),
]


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def format_finder_name(handle: Optional[str], name: str) -> str:
    return name


def format_telegram_handle(handle: Optional[str], name: str) -> str:
    if handle:
        return f"@{handle}"
    return name


def is_admin(user_id: int) -> bool:
    return bool(ADMIN_USER_ID) and str(user_id) == ADMIN_USER_ID


def parse_duck_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    cleaned = text.strip()
    if not re.fullmatch(r"\d+", cleaned):
        return None
    number = int(cleaned)
    if number < 1 or number > TOTAL_DUCKS:
        return None
    return number


def format_remaining_line(remaining: int) -> str:
    if remaining == 0:
        return "All ducks found! 🎉"
    return f"<b>{remaining}</b> duck(s) left."


def format_command_list(commands: list[tuple[str, str]]) -> str:
    return "\n".join(f"/{name} — {desc}" for name, desc in commands)


def to_bot_commands(commands: list[tuple[str, str]]) -> list[BotCommand]:
    return [BotCommand(name, desc) for name, desc in commands]


def clear_fail_state(user_id: int, duck_number: int) -> None:
    state.clear_fail_state(user_id, duck_number)


def clear_pending_overwrite(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("pending_overwrite", None)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🦆 <b>Welcome to the Duck Hunt!</b>\n\n"
        "<b>How to claim a duck:</b>\n"
        "1. Find a numbered resin duck (any color)\n"
        "2. <b>DM this bot</b> a photo of the duck (not in the group chat)\n"
        f"3. Put the duck number (1-{TOTAL_DUCKS}) in the photo caption\n\n"
        "Keep the resin ducks you find and hand them all to @MichelleChan when you can.\n\n"
        "<b>Prizes:</b> 🎁\n"
        "• Top hunter (most ducks) wins a small prize!\n"
        "• Lucky draw on duck numbers at the end too!\n\n"
        "Type /help for commands.\n\n"
        "⏰ <b>The hunt ends at 7:00 PM!</b> Good luck! 🍀",
        parse_mode=PARSE_MODE,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = [
        "<b>Player commands</b>",
        format_command_list(PLAYER_COMMANDS),
        "",
        "<b>How to claim:</b> DM this bot a photo with the duck number as the caption.",
    ]
    if is_admin(update.effective_user.id):
        lines.extend(
            [
                "",
                "<b>Admin commands</b>",
                format_command_list(ADMIN_COMMANDS),
            ]
        )
    await update.message.reply_text("\n".join(lines), parse_mode=PARSE_MODE)


async def leaderboard_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    entries = db.get_leaderboard(TOTAL_DUCKS)
    if not entries:
        await update.message.reply_text(
            "🦆 No ducks found yet. <b>Get hunting!</b>",
            parse_mode=PARSE_MODE,
        )
        return

    rank_emojis = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🏆 <b>Leaderboard</b>"]
    for rank, entry in enumerate(entries, start=1):
        display_name = escape_html(
            format_finder_name(entry.finder_handle, entry.finder_name)
        )
        prefix = rank_emojis.get(rank, f"{rank}.")
        lines.append(f"{prefix} {display_name} — <b>{entry.count}</b> duck(s)")
    await update.message.reply_text("\n".join(lines), parse_mode=PARSE_MODE)


async def remaining_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remaining = db.count_remaining(TOTAL_DUCKS)
    found = TOTAL_DUCKS - remaining
    if remaining == 0:
        await update.message.reply_text("All ducks found! 🎉", parse_mode=PARSE_MODE)
        return
    await update.message.reply_text(
        f"🔍 <b>{remaining}</b> duck(s) left out of {TOTAL_DUCKS}.\n"
        f"✅ <b>{found}</b> duck(s) found so far.",
        parse_mode=PARSE_MODE,
    )


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    message = update.message
    lines = [f"Chat ID: <code>{chat.id}</code>"]
    if chat.type == ChatType.PRIVATE:
        lines.append(
            "\nIn DM, this is your user ID. Put it in <code>ADMIN_USER_ID</code> in .env "
            "to enable admin commands and manual review requests."
        )
    if message and message.message_thread_id:
        lines.append(f"Topic ID: <code>{message.message_thread_id}</code>")
        lines.append(
            "\nPut Topic ID in <code>GROUP_TOPIC_ID</code> in .env "
            "so announcements go to <b>this</b> topic."
        )
        if message.message_thread_id == 1:
            lines.append(
                "\n⚠️ Topic ID 1 is usually <b>General</b>. "
                "Open the <b>Duck Hunt</b> topic and run /chatid there instead."
            )
    await update.message.reply_text("\n".join(lines), parse_mode=PARSE_MODE)


async def input_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return

    context.user_data["input_mode"] = True
    clear_pending_overwrite(context)
    saved = spots.count_saved(DUCK_SPOTS_DIR, TOTAL_DUCKS)
    await update.message.reply_text(
        "📥 <b>Input mode on.</b>\n\n"
        "Send a photo with the duck number (1–"
        f"{TOTAL_DUCKS}) as the caption.\n"
        f"Saved spots: <b>{saved}/{TOTAL_DUCKS}</b>\n\n"
        "Type /done when finished.",
        parse_mode=PARSE_MODE,
    )


async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return

    was_active = context.user_data.pop("input_mode", False)
    clear_pending_overwrite(context)
    if was_active:
        saved = spots.count_saved(DUCK_SPOTS_DIR, TOTAL_DUCKS)
        await update.message.reply_text(
            f"✅ Input mode off. <b>{saved}/{TOTAL_DUCKS}</b> spot photos saved.",
            parse_mode=PARSE_MODE,
        )
    else:
        await update.message.reply_text("Input mode was not active.", parse_mode=PARSE_MODE)


async def spot_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /spot &lt;duck number&gt;",
            parse_mode=PARSE_MODE,
        )
        return

    duck_number = parse_duck_number(context.args[0])
    if duck_number is None:
        await update.message.reply_text(
            f"Duck number must be an integer from <b>1</b> to <b>{TOTAL_DUCKS}</b>.",
            parse_mode=PARSE_MODE,
        )
        return

    image_bytes = spots.load_spot(DUCK_SPOTS_DIR, duck_number)
    if image_bytes is None:
        await update.message.reply_text(
            f"No spot photo saved for duck <b>#{duck_number}</b>.",
            parse_mode=PARSE_MODE,
        )
        return

    await update.message.reply_photo(
        photo=image_bytes,
        caption=f"🦆 Duck <b>#{duck_number}</b> hiding spot",
        parse_mode=PARSE_MODE,
    )


async def missing_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return

    missing = spots.list_missing(DUCK_SPOTS_DIR, TOTAL_DUCKS)
    if not missing:
        await update.message.reply_text(
            f"All <b>{TOTAL_DUCKS}</b> spot photos are saved.",
            parse_mode=PARSE_MODE,
        )
        return

    saved = TOTAL_DUCKS - len(missing)
    numbers_text = ", ".join(str(n) for n in missing)
    text = (
        f"<b>{saved}/{TOTAL_DUCKS}</b> spot photos saved.\n\n"
        f"<b>Missing ({len(missing)}):</b> {numbers_text}"
    )
    if len(text) > 4000:
        await update.message.reply_text(
            f"<b>{saved}/{TOTAL_DUCKS}</b> spot photos saved.\n"
            f"<b>{len(missing)}</b> ducks still missing. Numbers are too many to list here — "
            "check which files are absent in the duck_spots folder.",
            parse_mode=PARSE_MODE,
        )
        return
    await update.message.reply_text(text, parse_mode=PARSE_MODE)


async def start_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return

    state.game_active = True
    state.save()
    await update.message.reply_text(
        "🟢 <b>Duck hunt is open!</b> Players can submit claims now.",
        parse_mode=PARSE_MODE,
    )
    if GROUP_CHAT_ID:
        try:
            await announce_in_group(context, "🟢 <b>The duck hunt has started!</b> Good luck! 🦆")
        except Exception:
            logger.exception("Failed to announce hunt start in group")


async def end_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return

    state.game_active = False
    state.save()
    await update.message.reply_text(
        "🔴 <b>Duck hunt is closed.</b> No new claims will be accepted.",
        parse_mode=PARSE_MODE,
    )
    if GROUP_CHAT_ID:
        try:
            await announce_in_group(context, "🔴 <b>The duck hunt has ended!</b> Thanks for playing! 🦆")
        except Exception:
            logger.exception("Failed to announce hunt end in group")


async def announce_in_group(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    if not GROUP_CHAT_ID:
        return
    kwargs: dict = {
        "chat_id": int(GROUP_CHAT_ID),
        "text": text,
        "parse_mode": PARSE_MODE,
    }
    if GROUP_TOPIC_ID:
        kwargs["message_thread_id"] = int(GROUP_TOPIC_ID)
    await context.bot.send_message(**kwargs)


async def complete_claim(
    context: ContextTypes.DEFAULT_TYPE,
    duck_number: int,
    finder_user_id: int,
    finder_handle: Optional[str],
    finder_name: str,
    reply_message=None,
) -> tuple[bool, str]:
    """Record a claim and announce. Returns (success, message_for_caller)."""
    claimed = db.claim_duck(
        duck_number=duck_number,
        finder_user_id=finder_user_id,
        finder_handle=finder_handle,
        finder_name=finder_name,
    )
    if not claimed:
        existing = db.get_claim(duck_number)
        if existing is not None:
            finder = escape_html(
                format_finder_name(existing.finder_handle, existing.finder_name)
            )
            return False, f"Duck #{duck_number} was already claimed by {finder}."
        return False, "Something went wrong claiming that duck."

    clear_fail_state(finder_user_id, duck_number)
    remaining = db.count_remaining(TOTAL_DUCKS)
    finder_display = escape_html(format_finder_name(finder_handle, finder_name))
    success_text = (
        f"🎉 Duck <b>#{duck_number}</b> claimed! You're on the board. 🦆\n"
        f"{format_remaining_line(remaining)}"
    )

    if reply_message is not None:
        await reply_message.reply_text(success_text, parse_mode=PARSE_MODE)
    else:
        await context.bot.send_message(
            chat_id=finder_user_id,
            text=success_text,
            parse_mode=PARSE_MODE,
        )

    if GROUP_CHAT_ID:
        try:
            await announce_in_group(
                context,
                (
                    f"🦆 Duck <b>#{duck_number}</b> found by {finder_display}! 🎉\n"
                    f"{format_remaining_line(remaining)}"
                ),
            )
        except Exception:
            logger.exception(
                "Failed to announce duck #%s in group chat %s topic %s",
                duck_number,
                GROUP_CHAT_ID,
                GROUP_TOPIC_ID or "(general)",
            )

    return True, "Claim recorded."


async def notify_admin_review_request(
    context: ContextTypes.DEFAULT_TYPE,
    image_bytes: bytes,
    review_id: str,
    duck_number: int,
    user,
    reason: str,
) -> None:
    if not ADMIN_USER_ID:
        logger.warning(
            "Review request for duck #%s but ADMIN_USER_ID is not set",
            duck_number,
        )
        return

    finder = escape_html(
        format_telegram_handle(user.username, user.full_name or user.first_name)
    )
    note = escape_html(reason)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Accept", callback_data=f"approve:{review_id}"),
                InlineKeyboardButton("Reject", callback_data=f"reject:{review_id}"),
            ]
        ]
    )
    caption = (
        "📋 <b>Manual review requested</b>\n"
        f"Duck #: <b>{duck_number}</b>\n"
        f"From: {finder}\n"
        f"Note: {note}"
    )
    try:
        await context.bot.send_photo(
            chat_id=int(ADMIN_USER_ID),
            photo=image_bytes,
            caption=caption,
            parse_mode=PARSE_MODE,
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception(
            "Failed to send review request for duck #%s to admin %s",
            duck_number,
            ADMIN_USER_ID,
        )


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /remove &lt;duck number&gt;",
            parse_mode=PARSE_MODE,
        )
        return

    duck_number = parse_duck_number(context.args[0])
    if duck_number is None:
        await update.message.reply_text(
            f"Duck number must be an integer from <b>1</b> to <b>{TOTAL_DUCKS}</b>.",
            parse_mode=PARSE_MODE,
        )
        return

    removed = db.remove_claim(duck_number)
    if removed is None:
        await update.message.reply_text(
            f"No claim found for duck <b>#{duck_number}</b>.",
            parse_mode=PARSE_MODE,
        )
        return

    finder_display = escape_html(
        format_finder_name(removed.finder_handle, removed.finder_name)
    )
    remaining = db.count_remaining(TOTAL_DUCKS)

    await update.message.reply_text(
        f"Removed claim for duck <b>#{duck_number}</b> by {finder_display}.",
        parse_mode=PARSE_MODE,
    )

    if GROUP_CHAT_ID:
        try:
            await announce_in_group(
                context,
                (
                    f"⚠️ Duck <b>#{duck_number}</b> claim by {finder_display} was removed.\n"
                    f"{format_remaining_line(remaining)}"
                ),
            )
        except Exception:
            logger.exception(
                "Failed to announce removal of duck #%s in group chat %s",
                duck_number,
                GROUP_CHAT_ID,
            )


async def handle_spot_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    duck_number = parse_duck_number(message.caption)
    if duck_number is None:
        await message.reply_text(
            "📸 Send a photo with the duck number in the caption.\n"
            f"The caption must be an integer from <b>1</b> to <b>{TOTAL_DUCKS}</b> only.",
            parse_mode=PARSE_MODE,
        )
        return

    photo = message.photo[-1]
    photo_file = await photo.get_file()
    image_bytes = bytes(await photo_file.download_as_bytearray())

    if spots.spot_exists(DUCK_SPOTS_DIR, duck_number):
        attempt_id = uuid.uuid4().hex[:12]
        context.user_data["pending_overwrite"] = {
            "duck_number": duck_number,
            "file_id": photo.file_id,
            "attempt_id": attempt_id,
        }
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Confirm overwrite",
                        callback_data=f"spot_ok:{attempt_id}",
                    ),
                    InlineKeyboardButton(
                        "Cancel",
                        callback_data=f"spot_cancel:{attempt_id}",
                    ),
                ]
            ]
        )
        await message.reply_text(
            f"⚠️ Duck <b>#{duck_number}</b> already has a spot photo.\n"
            "Overwrite with this new photo?",
            parse_mode=PARSE_MODE,
            reply_markup=keyboard,
        )
        return

    clear_pending_overwrite(context)

    spots.save_spot(DUCK_SPOTS_DIR, duck_number, image_bytes)
    saved = spots.count_saved(DUCK_SPOTS_DIR, TOTAL_DUCKS)
    await message.reply_text(
        f"✅ Saved duck <b>#{duck_number}</b>. "
        f"<b>{saved}/{TOTAL_DUCKS}</b> spot photos recorded.",
        parse_mode=PARSE_MODE,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    await update.message.reply_text(
        "📸 To claim a duck, <b>DM this bot</b> a photo with the duck number in the caption.\n"
        f"The number must be an integer from <b>1</b> to <b>{TOTAL_DUCKS}</b>.\n\n"
        "Type /help for commands.",
        parse_mode=PARSE_MODE,
    )


async def handle_group_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📩 Please <b>DM this bot</b> to claim a duck — send your photo with the duck number "
        "in the caption there, not in the group chat.",
        parse_mode=PARSE_MODE,
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None:
        return

    user = message.from_user
    if is_admin(user.id) and context.user_data.get("input_mode"):
        await handle_spot_photo(update, context)
        return

    if not state.game_active:
        await message.reply_text(
            "🔴 The duck hunt is not accepting claims right now.",
            parse_mode=PARSE_MODE,
        )
        return

    duck_number = parse_duck_number(message.caption)
    if duck_number is None:
        await message.reply_text(
            "📸 Please send a photo with the duck number in the caption.\n"
            f"The caption must be an integer from <b>1</b> to <b>{TOTAL_DUCKS}</b> only.",
            parse_mode=PARSE_MODE,
        )
        return

    existing = db.get_claim(duck_number)
    if existing is not None:
        finder = escape_html(format_finder_name(existing.finder_handle, existing.finder_name))
        await message.reply_text(
            f"😅 Duck <b>#{duck_number}</b> was already found by {finder}.",
            parse_mode=PARSE_MODE,
        )
        return

    photo = message.photo[-1]
    photo_file = await photo.get_file()
    image_bytes = await photo_file.download_as_bytearray()
    mime_type = "image/jpeg"

    await message.reply_text("🔎 Checking your duck photo...")

    try:
        verification = verify_duck_photo(
            api_key=GEMINI_API_KEY,
            model=GEMINI_MODEL,
            image_bytes=bytes(image_bytes),
            mime_type=mime_type,
            claimed_number=duck_number,
        )
    except Exception:
        logger.exception("Gemini verification failed for duck #%s", duck_number)
        await message.reply_text(
            "Sorry, I couldn't verify that photo right now. Please try again."
        )
        return

    if not verification.match:
        streak = state.get_streak(user.id, duck_number) + 1
        attempt_id = uuid.uuid4().hex[:12]
        state.set_streak(user.id, duck_number, streak)
        state.set_pending(
            user.id,
            duck_number,
            {
                "file_id": photo.file_id,
                "reason": verification.reason,
                "finder_handle": user.username,
                "finder_name": user.full_name or user.first_name or "Unknown",
                "attempt_id": attempt_id,
            },
        )

        reject_text = (
            "<b>Could not verify your claim.</b> ❌\n\n"
            "Please retake the photo with the duck and its number clearly visible."
        )
        reply_markup = None
        if streak >= REVIEW_STREAK_THRESHOLD:
            reject_text += "\n\nTap below to ask @MichelleChan to review."
            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Ask Michelle to review",
                            callback_data=f"review:{duck_number}:{attempt_id}",
                        )
                    ]
                ]
            )

        await message.reply_text(
            reject_text,
            parse_mode=PARSE_MODE,
            reply_markup=reply_markup,
        )
        return

    success, fail_message = await complete_claim(
        context,
        duck_number=duck_number,
        finder_user_id=user.id,
        finder_handle=user.username,
        finder_name=user.full_name or user.first_name or "Unknown",
        reply_message=message,
    )
    if not success:
        await message.reply_text(fail_message, parse_mode=PARSE_MODE)


async def handle_callback_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    user = query.from_user

    if data.startswith("spot_ok:") or data.startswith("spot_cancel:"):
        if not is_admin(user.id):
            return

        attempt_id = data.split(":", 1)[1]
        pending = context.user_data.get("pending_overwrite")
        if pending is None or pending.get("attempt_id") != attempt_id:
            await query.message.reply_text("This overwrite prompt expired. Send the photo again.")
            return

        if data.startswith("spot_cancel:"):
            clear_pending_overwrite(context)
            await query.edit_message_text(
                f"❌ Overwrite cancelled. Duck <b>#{pending['duck_number']}</b> was not changed.",
                parse_mode=PARSE_MODE,
            )
            return

        try:
            tg_file = await context.bot.get_file(pending["file_id"])
            image_bytes = bytes(await tg_file.download_as_bytearray())
        except Exception:
            logger.exception(
                "Failed to download overwrite photo for duck #%s",
                pending["duck_number"],
            )
            await query.message.reply_text("Could not load the photo. Please send it again.")
            return

        duck_number = pending["duck_number"]
        spots.save_spot(DUCK_SPOTS_DIR, duck_number, image_bytes)
        clear_pending_overwrite(context)
        saved = spots.count_saved(DUCK_SPOTS_DIR, TOTAL_DUCKS)
        await query.edit_message_text(
            f"✅ Updated duck <b>#{duck_number}</b>. "
            f"<b>{saved}/{TOTAL_DUCKS}</b> spot photos saved.",
            parse_mode=PARSE_MODE,
        )
        return

    if data.startswith("review:"):
        parts = data.split(":", 2)
        if len(parts) != 3:
            await query.message.reply_text("Invalid review request.")
            return
        try:
            duck_number = int(parts[1])
            attempt_id = parts[2]
        except ValueError:
            await query.message.reply_text("Invalid review request.")
            return

        pending = state.get_pending(user.id, duck_number)
        if pending is None or pending.get("attempt_id") != attempt_id:
            await query.message.reply_text(
                "This review link expired. Please send a new photo."
            )
            return

        existing = db.get_claim(duck_number)
        if existing is not None:
            clear_fail_state(user.id, duck_number)
            finder = escape_html(
                format_finder_name(existing.finder_handle, existing.finder_name)
            )
            await query.message.reply_text(
                f"😅 Duck <b>#{duck_number}</b> was already found by {finder}.",
                parse_mode=PARSE_MODE,
            )
            return

        try:
            tg_file = await context.bot.get_file(pending["file_id"])
            image_bytes = bytes(await tg_file.download_as_bytearray())
        except Exception:
            logger.exception("Failed to download review photo for duck #%s", duck_number)
            await query.message.reply_text(
                "Could not load your photo. Please send it again."
            )
            return

        review_id = uuid.uuid4().hex[:12]
        state.set_admin_review(
            review_id,
            {
                "duck_number": duck_number,
                "finder_user_id": user.id,
                "finder_handle": pending["finder_handle"],
                "finder_name": pending["finder_name"],
                "reason": pending["reason"],
            },
        )
        clear_fail_state(user.id, duck_number)

        await notify_admin_review_request(
            context,
            image_bytes,
            review_id,
            duck_number,
            user,
            pending["reason"],
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "📨 Sent to @MichelleChan for review. You'll hear back soon.",
            parse_mode=PARSE_MODE,
        )
        return

    if data.startswith("approve:"):
        if not is_admin(user.id):
            return

        review_id = data.split(":", 1)[1]
        review = state.pop_admin_review(review_id)
        if review is None:
            await query.message.reply_text("Review no longer available.")
            return

        existing = db.get_claim(review["duck_number"])
        base_caption = query.message.caption or ""
        if existing is not None:
            finder = escape_html(
                format_finder_name(existing.finder_handle, existing.finder_name)
            )
            await query.edit_message_caption(
                caption=base_caption + f"\n\n❌ Already claimed by {finder}",
                parse_mode=PARSE_MODE,
                reply_markup=None,
            )
            return

        success, message = await complete_claim(
            context,
            duck_number=review["duck_number"],
            finder_user_id=review["finder_user_id"],
            finder_handle=review["finder_handle"],
            finder_name=review["finder_name"],
        )
        base_caption = query.message.caption or ""
        if success:
            await query.edit_message_caption(
                caption=base_caption + "\n\n✅ <b>Approved</b>",
                parse_mode=PARSE_MODE,
                reply_markup=None,
            )
        else:
            await query.edit_message_caption(
                caption=base_caption + f"\n\n❌ {escape_html(message)}",
                parse_mode=PARSE_MODE,
                reply_markup=None,
            )
        return

    if data.startswith("reject:"):
        if not is_admin(user.id):
            return

        review_id = data.split(":", 1)[1]
        review = state.pop_admin_review(review_id)
        if review is None:
            await query.message.reply_text("Review no longer available.")
            return

        await context.bot.send_message(
            chat_id=review["finder_user_id"],
            text=(
                f"Your duck <b>#{review['duck_number']}</b> claim was not approved. "
                "Please retake the photo and try again."
            ),
            parse_mode=PARSE_MODE,
        )
        base_caption = query.message.caption or ""
        await query.edit_message_caption(
            caption=base_caption + "\n\n❌ <b>Rejected</b>",
            parse_mode=PARSE_MODE,
            reply_markup=None,
        )


async def post_init(application: Application) -> None:
    group_commands = to_bot_commands(
        [
            ("leaderboard", "See who's found the most ducks"),
            ("remaining", "See how many ducks are left"),
            ("help", "List available commands"),
        ]
    )
    player_commands = to_bot_commands(PLAYER_COMMANDS)
    admin_commands = to_bot_commands(PLAYER_COMMANDS + ADMIN_COMMANDS)

    await application.bot.set_my_commands(
        group_commands,
        scope=BotCommandScopeAllGroupChats(),
    )
    await application.bot.set_my_commands(
        player_commands,
        scope=BotCommandScopeAllPrivateChats(),
    )
    if ADMIN_USER_ID:
        await application.bot.set_my_commands(
            admin_commands,
            scope=BotCommandScopeChat(chat_id=int(ADMIN_USER_ID)),
        )


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    if not GEMINI_API_KEY:
        raise SystemExit(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in."
        )

    inserted = db.seed_ducks(TOTAL_DUCKS)
    if inserted:
        logger.info("Seeded %s duck rows (1-%s).", inserted, TOTAL_DUCKS)
    else:
        logger.info("Duck table already seeded for 1-%s.", TOTAL_DUCKS)

    DUCK_SPOTS_DIR.mkdir(parents=True, exist_ok=True)

    if GROUP_CHAT_ID and not GROUP_TOPIC_ID:
        logger.warning(
            "GROUP_TOPIC_ID is not set — announcements will go to General. "
            "Run /chatid in the Duck Hunt topic and add the Topic ID to .env"
        )
    elif GROUP_CHAT_ID and GROUP_TOPIC_ID:
        logger.info(
            "Announcements will post to chat %s, topic %s",
            GROUP_CHAT_ID,
            GROUP_TOPIC_ID,
        )

    if not ADMIN_USER_ID:
        logger.warning(
            "ADMIN_USER_ID is not set — admin commands and manual review requests are disabled"
        )
    else:
        logger.info("Admin user ID: %s", ADMIN_USER_ID)

    if state.game_active:
        logger.info("Duck hunt is open for claims.")
    else:
        logger.warning("Duck hunt is closed — use /start_game to open claims.")

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("remaining", remaining_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("input_mode", input_mode_command))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(CommandHandler("spot", spot_command))
    application.add_handler(CommandHandler("missing", missing_command))
    application.add_handler(CommandHandler("start_game", start_game_command))
    application.add_handler(CommandHandler("end_game", end_game_command))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(
        MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_photo)
    )
    application.add_handler(
        MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, handle_group_photo)
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handle_text,
        )
    )

    logger.info("Duck Hunt bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
