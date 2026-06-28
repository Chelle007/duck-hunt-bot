"""Duck Hunt Telegram Bot."""

from __future__ import annotations

import html
import logging
import os
import re
from typing import Optional

from dotenv import load_dotenv
from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from db import DuckDatabase
from gemini import verify_duck_photo

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

db = DuckDatabase(DB_PATH)

PARSE_MODE = "HTML"


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
        "<b>Commands:</b>\n"
        "/leaderboard — see who's found the most ducks\n"
        "/remaining — see how many ducks are left\n\n"
        "⏰ <b>The hunt ends at 7:00 PM!</b> Good luck! 🍀",
        parse_mode=PARSE_MODE,
    )


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
            "to receive suspicious claim photos."
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


async def notify_admin_suspicious_claim(
    context: ContextTypes.DEFAULT_TYPE,
    image_bytes: bytes,
    duck_number: int,
    user,
    verification,
) -> None:
    if not ADMIN_USER_ID:
        logger.warning(
            "Suspicious claim for duck #%s but ADMIN_USER_ID is not set",
            duck_number,
        )
        return
    finder = escape_html(format_telegram_handle(user.username, user.full_name or user.first_name))
    note = escape_html(verification.suspicion_reason or verification.reason)
    caption = (
        "⚠️ <b>Suspicious duck claim</b>\n"
        f"Duck #: <b>{duck_number}</b>\n"
        f"From: {finder}\n"
        f"Note: {note}\n\n"
        f"Use /remove {duck_number} to remove this claim."
    )
    try:
        await context.bot.send_photo(
            chat_id=int(ADMIN_USER_ID),
            photo=image_bytes,
            caption=caption,
            parse_mode=PARSE_MODE,
        )
    except Exception:
        logger.exception(
            "Failed to send suspicious claim for duck #%s to admin %s",
            duck_number,
            ADMIN_USER_ID,
        )


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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    await update.message.reply_text(
        "📸 To claim a duck, <b>DM this bot</b> a photo with the duck number in the caption.\n"
        f"The number must be an integer from <b>1</b> to <b>{TOTAL_DUCKS}</b>.",
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
        await message.reply_text(
            "<b>Could not verify your claim.</b> ❌\n\n"
            "Please retake the photo with the duck and its number clearly visible.\n\n"
            "If it still fails, get it verified with @MichelleChan.",
            parse_mode=PARSE_MODE,
        )
        return

    user = message.from_user
    finder_user_id = user.id
    finder_handle = user.username
    finder_name = user.full_name or user.first_name or "Unknown"

    claimed = db.claim_duck(
        duck_number=duck_number,
        finder_user_id=finder_user_id,
        finder_handle=finder_handle,
        finder_name=finder_name,
    )
    if not claimed:
        existing = db.get_claim(duck_number)
        if existing is not None:
            finder = escape_html(format_finder_name(existing.finder_handle, existing.finder_name))
            await message.reply_text(
                f"🏃 Duck <b>#{duck_number}</b> was just claimed by {finder}. Too slow!",
                parse_mode=PARSE_MODE,
            )
        else:
            await message.reply_text(
                "Something went wrong claiming that duck. Please try again."
            )
        return

    remaining = db.count_remaining(TOTAL_DUCKS)
    finder_display = escape_html(format_finder_name(finder_handle, finder_name))

    await message.reply_text(
        f"🎉 Duck <b>#{duck_number}</b> claimed! You're on the board. 🦆\n"
        f"{format_remaining_line(remaining)}",
        parse_mode=PARSE_MODE,
    )

    if verification.suspicious:
        await notify_admin_suspicious_claim(
            context,
            bytes(image_bytes),
            duck_number,
            user,
            verification,
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


async def post_init(application: Application) -> None:
    group_commands = [
        BotCommand("leaderboard", "See who's found the most ducks"),
        BotCommand("remaining", "See how many ducks are left"),
    ]
    private_commands = [
        BotCommand("start", "Rules and how to claim"),
        *group_commands,
    ]
    await application.bot.set_my_commands(
        group_commands,
        scope=BotCommandScopeAllGroupChats(),
    )
    await application.bot.set_my_commands(
        private_commands,
        scope=BotCommandScopeAllPrivateChats(),
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

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("remaining", remaining_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("remove", remove_command))
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
