from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import aiosqlite
from datetime import date
from database import DB_PATH, ensure_user, get_user
from phrases import morning_text, get_random_challenge, get_level

TASKS = ["run", "reading", "project", "nutrition", "meditation"]
TASK_LABELS = {
    "run":        "🏃 Бег",
    "reading":    "📖 Чтение",
    "project":    "💻 Проект",
    "nutrition":  "🥗 Питание",
    "meditation": "🧘 Медитация",
}

def tasks_keyboard(done_tasks: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for key, label in TASK_LABELS.items():
        tick = "✅" if key in done_tasks else "☐"
        buttons.append([InlineKeyboardButton(
            f"{tick} {label}",
            callback_data=f"task_{key}"
        )])
    buttons.append([InlineKeyboardButton("📊 Мой прогресс", callback_data="my_stats")])
    buttons.append([InlineKeyboardButton("⚡ Случайный вызов", callback_data="challenge")])
    return InlineKeyboardMarkup(buttons)

async def get_done_tasks(db, user_id: int) -> list[str]:
    today = date.today().isoformat()
    async with db.execute(
        "SELECT task_key FROM daily_log WHERE user_id=? AND date=? AND done=1",
        (user_id, today)
    ) as cur:
        rows = await cur.fetchall()
    return [r[0] for r in rows]

async def cmd_morning(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        user = await ensure_user(db, uid, update.effective_user.first_name or "Хару")
        done = await get_done_tasks(db, uid)

    text = morning_text(user["name"], user["run_km"], user["streak"], user["xp"])
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=tasks_keyboard(done)
    )

async def task_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    today = date.today().isoformat()

    if query.data == "my_stats":
        await stats_inline(query, uid)
        return

    if query.data == "challenge":
        ch = get_random_challenge()
        await query.message.reply_text(
            f"💥 *Вызов дня:*\n\n{ch}\n\nВыполнил — нажми /done_challenge",
            parse_mode="Markdown"
        )
        return

    task_key = query.data.replace("task_", "")
    if task_key not in TASKS:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        user = await ensure_user(db, uid)
        done = await get_done_tasks(db, uid)

        if task_key in done:
            # Uncheck
            await db.execute(
                "DELETE FROM daily_log WHERE user_id=? AND date=? AND task_key=?",
                (uid, today, task_key)
            )
            done.remove(task_key)
        else:
            # Check + award XP
            from phrases import XP_TABLE
            xp_gain = XP_TABLE.get(task_key, 10)
            await db.execute(
                "INSERT OR IGNORE INTO daily_log (user_id, date, task_key, done) VALUES (?,?,?,1)",
                (uid, today, task_key)
            )
            await db.execute(
                "UPDATE user SET xp = xp + ? WHERE user_id=?",
                (xp_gain, uid)
            )
            done.append(task_key)

            # Check if all tasks done
            if all(t in done for t in TASKS):
                await _all_done(db, uid, query)

        await db.commit()
        user = await get_user(db, uid)

    await query.edit_message_reply_markup(reply_markup=tasks_keyboard(done))

async def _all_done(db, uid: int, query):
    from phrases import streak_message, XP_TABLE
    today = date.today().isoformat()

    # Update streak
    async with db.execute("SELECT streak, last_active, best_streak FROM user WHERE user_id=?", (uid,)) as cur:
        row = await cur.fetchone()

    streak, last_active, best = row
    from datetime import date as d, timedelta
    yesterday = (d.today() - timedelta(days=1)).isoformat()

    if last_active == yesterday:
        streak += 1
    elif last_active != today:
        streak = 1

    best = max(best, streak)
    bonus_xp = XP_TABLE.get("evening", 10)

    # Unlock Tailung mode at 30 days
    mode = "tailung" if streak >= 30 else "normal"

    await db.execute(
        "UPDATE user SET streak=?, best_streak=?, last_active=?, xp=xp+?, mode=? WHERE user_id=?",
        (streak, best, today, bonus_xp, mode, uid)
    )

    streak_msg = streak_message(streak)
    text = f"🎯 *ВСЕ ЗАДАЧИ ВЫПОЛНЕНЫ!*\n+{bonus_xp} XP за день\n🔥 Стрик: {streak} дней"
    if streak_msg:
        text += f"\n\n{streak_msg}"
    if streak == 30:
        text += "\n\n🐉 *РЕЖИМ ТАЙЛУНГА АКТИВИРОВАН!*\nС завтра нагрузки возрастают."

    await query.message.reply_text(text, parse_mode="Markdown")

async def stats_inline(query, uid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        user = await get_user(db, uid)
        if not user:
            await query.message.reply_text("Сначала /start")
            return

        # Projects
        async with db.execute(
            "SELECT name, emoji, metric_val, target FROM project WHERE user_id=? AND status='active'",
            (uid,)
        ) as cur:
            projects = await cur.fetchall()

        # Current book
        async with db.execute(
            "SELECT title, pages_done, pages_total FROM book WHERE user_id=? AND active=1",
            (uid,)
        ) as cur:
            book = await cur.fetchone()

    level = get_level(user["xp"])
    lines = [
        f"📊 *Дашборд — {user['name']}*\n",
        f"{level} | ⚡ {user['xp']} XP",
        f"🔥 Стрик: {user['streak']} дней (рекорд: {user['best_streak']})\n",
        "─────────────────",
        "🚀 *Проекты:*"
    ]

    if projects:
        for name, emoji, val, target in projects:
            pct = int(val / target * 100) if target else 0
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            lines.append(f"{emoji} {name}: {val:,}/{target:,}\n`{bar}` {pct}%")
    else:
        lines.append("_Добавь проекты через /add_project_")

    if book:
        pct = int(book[1] / book[2] * 100) if book[2] else 0
        lines.append(f"\n📖 *Книга:* {book[0]}\n{book[1]}/{book[2]} стр. ({pct}%)")

    await query.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown"
    )

morning_handler = CommandHandler("morning", cmd_morning)
task_cb_handler = CallbackQueryHandler(task_callback, pattern="^(task_|my_stats|challenge)")