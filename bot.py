# -*- coding: utf-8 -*-
"""
bot.py
ربات تلگرام بازی سنگ‌کاغذقیچی (اینلاین).

نحوه کار:
 1) کاربر در هر چتی می‌نویسد: @yourbotname  -> یک نتیجه‌ی اینلاین با عنوان
    "بازی سنگ کاغذ قیچی" نشان داده می‌شود.
 2) با ارسال آن، پیامی با دکمه‌ی «منم می‌خوام بازی کنم 🎮» و «شروع 🚀» در همان
    چت قرار می‌گیرد و اسم فرستنده به‌عنوان شرکت‌کننده‌ی اول ثبت می‌شود.
 3) وقتی نفر دوم روی «منم می‌خوام بازی کنم» کلیک کند، اسمش به‌عنوان
    شرکت‌کننده‌ی دوم ثبت می‌شود.
 4) فقط شروع‌کننده می‌تواند دکمه‌ی «شروع» را بزند. با زدن آن هر دو بازیکن
    (هرکدام به‌صورت خصوصی، با popup/alert تلگرام) دکمه‌های سنگ/کاغذ/قیچی
    را می‌بینند.
 5) ربات تا انتخاب هر دو نفر صبر می‌کند، نتیجه‌ی آن دست را در پیام اصلی
    اعلام می‌کند. بعد از ۳ دست، برنده‌ی نهایی اعلام می‌شود.
 6) بعد از پایان هر بازی (در هر گروهی)، خلاصه‌ی کامل به پیوی آیدی عددی
    ADMIN_REPORT_ID ارسال می‌شود.
"""

import logging
import uuid

from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    InlineQueryHandler,
    ChosenInlineResultHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.error import TelegramError

import database as db

# -------------------------------------------------------------------------
# تنظیمات
# -------------------------------------------------------------------------

BOT_TOKEN = "PUT_YOUR_BOT_TOKEN_HERE"  # توکن ربات را از @BotFather بگیرید

# آیدی عددی که بعد از پایان هر بازی (در هر گروهی)، خلاصه‌ی کامل بازی
# برایش در پیوی ارسال می‌شود.
ADMIN_REPORT_ID = 5283015101

CHOICES = {
    "rock": {"label": "سنگ", "emoji": "✊"},
    "paper": {"label": "کاغذ", "emoji": "✋"},
    "scissors": {"label": "قیچی", "emoji": "✌️"},
}

WIN_MAP = {
    ("rock", "scissors"): "p1",
    ("scissors", "paper"): "p1",
    ("paper", "rock"): "p1",
}

TOTAL_ROUNDS = 3

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# توابع کمکی
# -------------------------------------------------------------------------

def mention(user_id: int, name: str) -> str:
    """ساخت یک منشن HTML امن برای نام کاربر."""
    safe_name = (name or "بازیکن").replace("<", "").replace(">", "")
    return f'<a href="tg://user?id={user_id}">{safe_name}</a>'


def decide_round_winner(p1_choice: str, p2_choice: str) -> str:
    """برگرداندن 'p1' یا 'p2' یا 'draw'."""
    if p1_choice == p2_choice:
        return "draw"
    if (p1_choice, p2_choice) in WIN_MAP:
        return "p1"
    return "p2"


def build_lobby_keyboard(game_id: str, p2_joined: bool) -> InlineKeyboardMarkup:
    rows = []
    if not p2_joined:
        rows.append(
            [InlineKeyboardButton("منم می‌خوام بازی کنم 🎮", callback_data=f"join:{game_id}")]
        )
    rows.append([InlineKeyboardButton("شروع 🚀", callback_data=f"go:{game_id}")])
    return InlineKeyboardMarkup(rows)


def build_choice_keyboard(game_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("سنگ ✊", callback_data=f"pick:{game_id}:rock"),
                InlineKeyboardButton("کاغذ ✋", callback_data=f"pick:{game_id}:paper"),
                InlineKeyboardButton("قیچی ✌️", callback_data=f"pick:{game_id}:scissors"),
            ]
        ]
    )


def build_lobby_text(game: dict) -> str:
    p1_text = mention(game["p1_id"], game["p1_name"])
    p2_text = mention(game["p2_id"], game["p2_name"]) if game["p2_id"] else "—— منتظر نفر دوم ——"
    return (
        "🎮 <b>بازی سنگ کاغذ قیچی</b>\n\n"
        f"شرکت‌کننده اول: {p1_text}\n"
        f"شرکت‌کننده دوم: {p2_text}\n\n"
        "وقتی هر دو نفر مشخص شدند، شروع‌کننده‌ی بازی می‌تواند دکمه‌ی «شروع» را بزند."
    )


def build_round_status_text(game: dict, extra: str = "") -> str:
    p1_text = mention(game["p1_id"], game["p1_name"])
    p2_text = mention(game["p2_id"], game["p2_name"])
    header = (
        "🎮 <b>بازی سنگ کاغذ قیچی</b>\n\n"
        f"{p1_text}  🆚  {p2_text}\n"
        f"امتیاز: {game['p1_score']} - {game['p2_score']}\n"
        f"دست {game['current_round']} از {TOTAL_ROUNDS}\n"
    )
    if extra:
        header += f"\n{extra}"
    return header


async def edit_lobby_message(context: ContextTypes.DEFAULT_TYPE, game: dict, text: str,
                              keyboard: InlineKeyboardMarkup = None):
    """ادیت پیام بازی - چه در چت معمولی چه در حالت اینلاین."""
    try:
        if game.get("inline_message_id"):
            await context.bot.edit_message_text(
                inline_message_id=game["inline_message_id"],
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await context.bot.edit_message_text(
                chat_id=game["chat_id"],
                message_id=game["message_id"],
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
    except TelegramError as e:
        logger.warning("خطا در ادیت پیام بازی %s: %s", game["game_id"], e)


async def send_admin_move(context: ContextTypes.DEFAULT_TYPE, game: dict, player: str, choice: str):
    """ارسال لحظه‌ای انتخاب هر بازیکن به پیوی ادمین."""
    choice_label = CHOICES[choice]["label"] + " " + CHOICES[choice]["emoji"]
    if player == "p1":
        player_name = game["p1_name"]
        player_id = game["p1_id"]
        opponent_name = game["p2_name"]
    else:
        player_name = game["p2_name"]
        player_id = game["p2_id"]
        opponent_name = game["p1_name"]

    text = (
        f"🎯 <b>انتخاب لحظه‌ای</b>\n\n"
        f"بازی: <code>{game['game_id']}</code>\n"
        f"بازیکن: {player_name} (ID: <code>{player_id}</code>)\n"
        f"حریف: {opponent_name}\n"
        f"انتخاب: {choice_label}\n"
        f"دست {game['current_round']} از {TOTAL_ROUNDS}"
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_REPORT_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as e:
        logger.warning("ارسال انتخاب لحظه‌ای به ادمین ناموفق بود: %s", e)


async def send_admin_report(context: ContextTypes.DEFAULT_TYPE, game: dict):
    """ارسال خلاصه‌ی کامل بازی به پیوی ادمین، بعد از پایان هر بازی."""
    rounds = db.get_rounds(game["game_id"])
    p1_name = game["p1_name"]
    p2_name = game["p2_name"]

    lines = [
        "📋 <b>گزارش پایان بازی</b>",
        f"بازیکن ۱: {p1_name} (ID: {game['p1_id']})",
        f"بازیکن ۲: {p2_name} (ID: {game['p2_id']})",
        "",
    ]
    for i, r in enumerate(rounds, start=1):
        p1_c = CHOICES[r["p1"]]["label"] + " " + CHOICES[r["p1"]]["emoji"]
        p2_c = CHOICES[r["p2"]]["label"] + " " + CHOICES[r["p2"]]["emoji"]
        if r["winner"] == "draw":
            res = "مساوی"
        elif r["winner"] == "p1":
            res = f"برد {p1_name}"
        else:
            res = f"برد {p2_name}"
        lines.append(f"دست {i}: {p1_name} = {p1_c} | {p2_name} = {p2_c} → {res}")

    lines.append("")
    if game["p1_score"] > game["p2_score"]:
        winner_line = f"🏆 برنده نهایی: {p1_name} ({game['p1_score']} - {game['p2_score']})"
    elif game["p2_score"] > game["p1_score"]:
        winner_line = f"🏆 برنده نهایی: {p2_name} ({game['p1_score']} - {game['p2_score']})"
    else:
        winner_line = f"🤝 نتیجه نهایی مساوی ({game['p1_score']} - {game['p2_score']})"
    lines.append(winner_line)

    try:
        await context.bot.send_message(
            chat_id=ADMIN_REPORT_ID,
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as e:
        logger.warning("ارسال گزارش به ادمین ناموفق بود: %s", e)


# -------------------------------------------------------------------------
# هندلر دستور /start
# -------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_username = context.bot.username
    text = (
        "سلام! 👋\n"
        "برای شروع بازی سنگ کاغذ قیچی:\n\n"
        f"🔹 <b>روش اینلاین:</b> در هر چتی بنویسید <code>@{bot_username}</code>\n"
        f"🔹 <b>روش دستی:</b> دستور /newgame را بزنید\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def newgame_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع بازی جدید با دستور /newgame - جایگزین inline."""
    user = update.effective_user
    game_id = str(uuid.uuid4())[:12]
    db.create_game(game_id, chat_id=update.effective_chat.id, p1_id=user.id, p1_name=user.full_name)

    game = db.get_game(game_id)
    text = build_lobby_text(game)
    keyboard = build_lobby_keyboard(game_id, p2_joined=False)

    sent = await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    db.set_message_ref(game_id, chat_id=sent.chat_id, message_id=sent.message_id)
    logger.info("بازی جدید %s با /newgame ساخته شد.", game_id)


# -------------------------------------------------------------------------
# هندلر inline query
# -------------------------------------------------------------------------

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    result = InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title="🎮 بازی سنگ کاغذ قیچی",
        description="یک بازی سنگ کاغذ قیچی با دوستانت در این چت شروع کن!",
        input_message_content=InputTextMessageContent(
            "🎮 <b>بازی سنگ کاغذ قیچی</b>\n\nدر حال آماده‌سازی بازی...",
            parse_mode=ParseMode.HTML,
        ),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("در حال بارگذاری...", callback_data="noop")]]
        ),
    )
    await query.answer([result], cache_time=1, is_personal=True)
    logger.info("inline query از کاربر %s دریافت شد.", query.from_user.id)


# -------------------------------------------------------------------------
# هندلر chosen_inline_result -> وقتی کاربر واقعاً نتیجه را ارسال کرد
# -------------------------------------------------------------------------

async def chosen_inline_result_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chosen = update.chosen_inline_result
    user = chosen.from_user
    inline_message_id = chosen.inline_message_id

    logger.info("=== chosen_inline_result handler شروع شد ===")
    logger.info("user=%s (%s), inline_msg_id=%s", user.id, user.full_name, inline_message_id)

    if not inline_message_id:
        logger.error("inline_message_id خالی بود! کلاینت آن را نفرستاده.")
        return

    game_id = str(uuid.uuid4())[:12]
    db.create_game(game_id, chat_id=None, p1_id=user.id, p1_name=user.full_name)
    db.set_message_ref(game_id, inline_message_id=inline_message_id)

    game = db.get_game(game_id)
    text = build_lobby_text(game)
    keyboard = build_lobby_keyboard(game_id, p2_joined=False)

    # روش ۱: edit_message_text
    try:
        await context.bot.edit_message_text(
            inline_message_id=inline_message_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        logger.info("روش ۱ (edit_message_text) موفق بود. game_id=%s", game_id)
        return
    except TelegramError as e:
        logger.warning("روش ۱ (edit_message_text) ناموفق: %s", e)

    # روش ۲: edit_message_reply_markup (فقط کیبورد را عوض کن)
    try:
        await context.bot.edit_message_reply_markup(
            inline_message_id=inline_message_id,
            reply_markup=keyboard,
        )
        logger.info("روش ۲ (edit_message_reply_markup) موفق بود. game_id=%s", game_id)
        return
    except TelegramError as e:
        logger.warning("روش ۲ (edit_message_reply_markup) ناموفق: %s", e)

    # روش ۳: send_message به پیوی کاربر
    try:
        sent = await context.bot.send_message(
            chat_id=user.id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        db.set_message_ref(game_id, chat_id=sent.chat_id, message_id=sent.message_id)
        logger.info("روش ۳ (send_message به پیوی) موفق بود. game_id=%s", game_id)
    except TelegramError as e2:
        logger.error("روش ۳ هم ناموفق: %s", e2)


# -------------------------------------------------------------------------
# هندلر اصلی دکمه‌ها (callback_query)
# -------------------------------------------------------------------------

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user

    if data == "noop":
        await query.answer()
        return

    action, _, rest = data.partition(":")

    # ---------------- پیوستن نفر دوم ----------------
    if action == "join":
        game_id = rest
        game = db.get_game(game_id)
        if not game:
            await query.answer("این بازی دیگر در دسترس نیست.", show_alert=True)
            return

        if game["p1_id"] == user.id:
            await query.answer("نمی‌توانید با خودتان بازی کنید! منتظر نفر دیگری باشید.", show_alert=True)
            return

        if game["p2_id"] is not None:
            await query.answer("این بازی قبلاً تکمیل شده است.", show_alert=True)
            return

        joined = db.join_game(game_id, user.id, user.full_name)
        if not joined:
            await query.answer("نتوانستید به این بازی بپیوندید.", show_alert=True)
            return

        await query.answer("به بازی پیوستید! ✅")
        game = db.get_game(game_id)
        text = build_lobby_text(game)
        keyboard = build_lobby_keyboard(game_id, p2_joined=True)
        await edit_lobby_message(context, game, text, keyboard)
        return

    # ---------------- شروع بازی ----------------
    if action == "go":
        game_id = rest
        game = db.get_game(game_id)
        if not game:
            await query.answer("این بازی دیگر در دسترس نیست.", show_alert=True)
            return

        if user.id != game["p1_id"]:
            await query.answer("فقط شروع‌کننده‌ی بازی می‌تواند آن را آغاز کند.", show_alert=True)
            return

        if not game["p2_id"]:
            await query.answer("هنوز نفر دوم به بازی نپیوسته است.", show_alert=True)
            return

        if game["status"] not in ("ready",):
            await query.answer("بازی در حال انجام است.", show_alert=True)
            return

        db.start_round(game_id)
        game = db.get_game(game_id)

        await query.answer("بازی شروع شد! انتخابت رو با دکمه‌های زیر (که فقط خودت می‌بینی) انجام بده.", show_alert=True)

        text = build_round_status_text(
            game, extra="⏳ هر دو بازیکن باید انتخاب خود را انجام دهند..."
        )
        # دکمه‌های عمومی روی پیام اصلی هم سنگ/کاغذ/قیچی می‌شوند؛
        # تلگرام تشخیص نمی‌دهد چه کسی کلیک می‌کند، پس در خود
        # callback handler چک می‌کنیم که فقط p1 و p2 بتوانند انتخاب کنند
        # و انتخاب هرکس فقط به خودش با popup alert نشان داده می‌شود.
        keyboard = build_choice_keyboard(game_id)
        await edit_lobby_message(context, game, text, keyboard)
        return

    # ---------------- انتخاب سنگ/کاغذ/قیچی ----------------
    if action == "pick":
        game_id, _, choice = rest.partition(":")
        game = db.get_game(game_id)
        if not game:
            await query.answer("این بازی دیگر در دسترس نیست.", show_alert=True)
            return

        if game["status"] != "round_in_progress":
            await query.answer("الان زمان انتخاب نیست.", show_alert=True)
            return

        if user.id == game["p1_id"]:
            slot = "p1"
            already = game["p1_current_choice"]
        elif user.id == game["p2_id"]:
            slot = "p2"
            already = game["p2_current_choice"]
        else:
            await query.answer("شما در این بازی شرکت‌کننده نیستید.", show_alert=True)
            return

        if already:
            await query.answer("شما قبلاً انتخاب کرده‌اید. منتظر حریف باشید...", show_alert=True)
            return

        db.set_choice(game_id, slot, choice)
        label = CHOICES[choice]["label"] + " " + CHOICES[choice]["emoji"]
        await query.answer(f"انتخاب شما ثبت شد: {label}", show_alert=True)

        await send_admin_move(context, game, slot, choice)

        game = db.get_game(game_id)
        p1_done = bool(game["p1_current_choice"])
        p2_done = bool(game["p2_current_choice"])

        if p1_done and p2_done:
            # هر دو انتخاب کردند -> نتیجه‌ی دست را محاسبه کن
            p1_choice = game["p1_current_choice"]
            p2_choice = game["p2_current_choice"]
            round_winner = decide_round_winner(p1_choice, p2_choice)
            db.finalize_round(game_id, p1_choice, p2_choice, round_winner)
            game = db.get_game(game_id)

            p1_label = CHOICES[p1_choice]["label"] + " " + CHOICES[p1_choice]["emoji"]
            p2_label = CHOICES[p2_choice]["label"] + " " + CHOICES[p2_choice]["emoji"]

            if round_winner == "draw":
                result_line = f"🤝 این دست مساوی شد ({p1_label} مقابل {p2_label})"
            elif round_winner == "p1":
                result_line = f"🏅 برنده‌ی این دست: {mention(game['p1_id'], game['p1_name'])} ({p1_label} مقابل {p2_label})"
            else:
                result_line = f"🏅 برنده‌ی این دست: {mention(game['p2_id'], game['p2_name'])} ({p1_label} مقابل {p2_label})"

            if game["current_round"] >= TOTAL_ROUNDS:
                # پایان بازی
                db.finish_game(game_id)
                game = db.get_game(game_id)

                if game["p1_score"] > game["p2_score"]:
                    final_line = f"🏆 برنده‌ی نهایی بازی: {mention(game['p1_id'], game['p1_name'])}!"
                elif game["p2_score"] > game["p1_score"]:
                    final_line = f"🏆 برنده‌ی نهایی بازی: {mention(game['p2_id'], game['p2_name'])}!"
                else:
                    final_line = "🤝 بازی با نتیجه‌ی مساوی به پایان رسید!"

                text = build_round_status_text(game, extra=f"{result_line}\n\n{final_line}")
                await edit_lobby_message(context, game, text, keyboard=None)

                # ارسال گزارش کامل به ادمین
                await send_admin_report(context, game)
            else:
                # برو به دست بعدی
                text = build_round_status_text(
                    game,
                    extra=f"{result_line}\n\n⏳ دست بعدی... هر دو بازیکن دکمه‌ی زیر را بزنند.",
                )
                # برای شروع خودکار دست بعد، یک دکمه‌ی «دست بعد» به شروع‌کننده می‌دهیم
                next_keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("دست بعد ▶️", callback_data=f"next:{game_id}")]]
                )
                await edit_lobby_message(context, game, text, next_keyboard)
        return

    # ---------------- شروع دست بعدی ----------------
    if action == "next":
        game_id = rest
        game = db.get_game(game_id)
        if not game:
            await query.answer("این بازی دیگر در دسترس نیست.", show_alert=True)
            return

        if user.id not in (game["p1_id"], game["p2_id"]):
            await query.answer("شما در این بازی شرکت‌کننده نیستید.", show_alert=True)
            return

        if game["status"] == "finished":
            await query.answer("این بازی قبلاً پایان یافته است.", show_alert=True)
            return

        db.start_round(game_id)
        game = db.get_game(game_id)
        await query.answer("دست بعدی شروع شد!")

        text = build_round_status_text(
            game, extra="⏳ هر دو بازیکن باید انتخاب خود را انجام دهند..."
        )
        keyboard = build_choice_keyboard(game_id)
        await edit_lobby_message(context, game, text, keyboard)
        return

    # عملیات ناشناخته
    await query.answer()


# -------------------------------------------------------------------------
# اجرای برنامه
# -------------------------------------------------------------------------

def main():
    db.init_db()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("newgame", newgame_command))
    application.add_handler(InlineQueryHandler(inline_query_handler))
    application.add_handler(ChosenInlineResultHandler(chosen_inline_result_handler))
    application.add_handler(CallbackQueryHandler(callback_query_handler))

    logger.info("ربات در حال اجراست...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
