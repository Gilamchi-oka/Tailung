import asyncio
import logging
import os
from datetime import time

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import init_db, DB_PATH
import aiosqlite

from morning import morning_handler, task_cb_handler
from evening import evening_handler, evening_cb_handler
from projects import (
    add_project_handler, list_projects_handler, update_project_handler,
    project_cb_handler
)
from books import (
    add_book_handler, book_progress_handler, book_cb_handler
)
from weekly import weekly_handler, weekly_cb_handler
from stats import stats_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN", "")


# ── Автоматическая рассылка утром и вечером ──────────────────────────────────

async def send_morning_all(app: Application):
    """Отправить утренние задания всем пользователям в 7:00"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM user") as cur:
            users = await cur.fetchall()

    from morning import build_morning_message, tasks_keyboard
    from database import get_user

    for (uid,) in users:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                user = await get_user(db, uid)
                # Прогрессия бега: +0.5 км каждую неделю
                week = user.get("week_num", 0)
                current_week = (
                    __import__("datetime").date.today().isocalendar()[1]
                )
                if user.get("last_week") != current_week:
                    new_km = round(user["run_km"] + 0.5, 1)
                    await db.execute(
                        "UPDATE user SET run_km=?, week_num=?, last_week=? WHERE user_id=?",
                        (new_km, week + 1, current_week, uid)
                    )
                    await db.commit()
                    user = await get_user(db, uid)

            from phrases import morning_text
            from morning import tasks_keyboard
            from database import get_user
            async with aiosqlite.connect(DB_PATH) as db:
                user = await get_user(db, uid)
                async with db.execute(
                    "SELECT task_key FROM daily_log WHERE user_id=? AND date=? AND done=1",
                    (uid, __import__("datetime").date.today().isoformat())
                ) as cur:
                    done = [r[0] for r in await cur.fetchall()]

            text = morning_text(user["name"], user["run_km"], user["streak"], user["xp"])
            await app.bot.send_message(
                chat_id=uid,
                text=text,
                parse_mode="Markdown",
                reply_markup=tasks_keyboard(done)
            )
        except Exception as e:
            logger.warning(f"Morning send failed for {uid}: {e}")


async def send_evening_all(app: Application):
    """Вечерний отчёт всем в 21:00"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, name FROM user") as cur:
            users = await cur.fetchall()

    from phrases import evening_text
    from evening import cmd_evening_text

    for (uid, name) in users:
        try:
            text, keyboard = cmd_evening_text(name)
            await app.bot.send_message(
                chat_id=uid,
                text=text,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.warning(f"Evening send failed for {uid}: {e}")


async def send_weekly_review_all(app: Application):
    """Воскресенье 20:00 — еженедельное ревью"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM user") as cur:
            users = await cur.fetchall()

    for (uid,) in users:
        try:
            from weekly import start_weekly_review
            await start_weekly_review(app.bot, uid)
        except Exception as e:
            logger.warning(f"Weekly review failed for {uid}: {e}")


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name or "Хару"

    async with aiosqlite.connect(DB_PATH) as db:
        from database import ensure_user
        user = await ensure_user(db, uid, name)

    text = (
        f"🥋 *Приветствую, {user['name']}.*\n\n"
        f"Я — Шифу. Твой наставник, пока ты не стал Тайлунгом.\n\n"
        f"Вот что я умею:\n"
        f"• Каждое утро в *7:00* — задания на день\n"
        f"• Каждый вечер в *21:00* — вечерний отчёт\n"
        f"• Каждое воскресенье — еженедельный разбор\n\n"
        f"*Команды:*\n"
        f"/morning — утреннее задание прямо сейчас\n"
        f"/evening — вечерний отчёт\n"
        f"/stats — твой дашборд\n"
        f"/add\_project — добавить проект\n"
        f"/projects — список проектов\n"
        f"/add\_book — добавить книгу\n"
        f"/weekly — еженедельный обзор\n\n"
        f"Начнём. /morning"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Команды Шифу:*\n\n"
        "/morning — задания на сегодня\n"
        "/evening — вечерний отчёт\n"
        "/stats — дашборд: XP, стрик, проекты\n"
        "/add\_project `Название Цель` — добавить проект\n"
        "/projects — все проекты\n"
        "/update\_project — обновить метрику проекта\n"
        "/add\_book `Название Страниц` — добавить книгу\n"
        "/book\_progress `страниц` — отметить страницы\n"
        "/weekly — запустить еженедельное ревью\n",
        parse_mode="Markdown"
    )


# ── main ──────────────────────────────────────────────────────────────────────

async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("morning", "Задания на сегодня"),
        BotCommand("evening", "Вечерний отчёт"),
        BotCommand("stats", "Дашборд"),
        BotCommand("projects", "Мои проекты"),
        BotCommand("add_project", "Добавить проект"),
        BotCommand("add_book", "Добавить книгу"),
        BotCommand("weekly", "Еженедельный обзор"),
        BotCommand("help", "Помощь"),
    ])


def main():
    asyncio.get_event_loop().run_until_complete(init_db())

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(morning_handler)
    app.add_handler(task_cb_handler)
    app.add_handler(evening_handler)
    app.add_handler(evening_cb_handler)
    app.add_handler(stats_handler)
    app.add_handler(add_project_handler)
    app.add_handler(list_projects_handler)
    app.add_handler(update_project_handler)
    app.add_handler(project_cb_handler)
    app.add_handler(add_book_handler)
    app.add_handler(book_progress_handler)
    app.add_handler(book_cb_handler)
    app.add_handler(weekly_handler)
    app.add_handler(weekly_cb_handler)

    # Scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(
        send_morning_all, "cron", hour=7, minute=0,
        args=[app]
    )
    scheduler.add_job(
        send_evening_all, "cron", hour=21, minute=0,
        args=[app]
    )
    scheduler.add_job(
        send_weekly_review_all, "cron",
        day_of_week="sun", hour=20, minute=0,
        args=[app]
    )
    scheduler.start()

    logger.info("Шифу запущен. Ждём учеников.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()