from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
import aiosqlite
from datetime import date, timedelta
from database import DB_PATH, get_user, ensure_user
from phrases import evening_text, fail_message, streak_message, XP_TABLE, get_level

ASK_RUN, ASK_READING, ASK_PROJECT, ASK_NUTRITION, ASK_NOTES = range(5)

async def cmd_evening(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        user = await ensure_user(db, uid)

    text = evening_text(user["name"])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏃 Бег выполнен", callback_data="ev_run_1"),
         InlineKeyboardButton("🏃 Не бегал", callback_data="ev_run_0")],
        [InlineKeyboardButton("📖 Читал", callback_data="ev_read_1"),
         InlineKeyboardButton("📖 Не читал", callback_data="ev_read_0")],
        [InlineKeyboardButton("💻 Работал над проектом", callback_data="ev_proj_1"),
         InlineKeyboardButton("💻 Не работал", callback_data="ev_proj_0")],
        [InlineKeyboardButton("🥗 Питание чистое", callback_data="ev_nut_1"),
         InlineKeyboardButton("🥗 Питание провал", callback_data="ev_nut_0")],
        [InlineKeyboardButton("🧘 Медитировал", callback_data="ev_med_1"),
         InlineKeyboardButton("🧘 Не медитировал", callback_data="ev_med_0")],
    ])
    await update.message.reply_text(text, reply_markup=keyboard)

async def evening_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data  # ev_run_1 / ev_run_0 etc

    parts = data.split("_")
    task_map = {"run": "run", "read": "reading", "proj": "project", "nut": "nutrition", "med": "meditation"}
    short = parts[1]
    task_key = task_map.get(short)
    done = int(parts[2])

    today = date.today().isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        user = await ensure_user(db, uid)

        # Log the task
        await db.execute(
            "INSERT OR REPLACE INTO daily_log (user_id, date, task_key, done) VALUES (?,?,?,?)",
            (uid, today, task_key, done)
        )

        if done:
            xp_gain = XP_TABLE.get(task_key, 10)
            await db.execute("UPDATE user SET xp=xp+? WHERE user_id=?", (xp_gain, uid))

        # Get all evening results
        async with db.execute(
            "SELECT task_key, done FROM daily_log WHERE user_id=? AND date=?",
            (uid, today)
        ) as cur:
            rows = await cur.fetchall()

        await db.commit()
        user = await get_user(db, uid)

    results = {r[0]: r[1] for r in rows}
    tasks_answered = sum(1 for k in ["run","reading","project","nutrition","meditation"] if k in results)

    if tasks_answered >= 5:
        await _show_day_summary(query, uid, results, user)
    else:
        await query.edit_message_text(
            f"✅ Записал. Продолжай отмечать остальные задачи.",
            reply_markup=query.message.reply_markup
        )

async def _show_day_summary(query, uid: int, results: dict, user: dict):
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    done_count = sum(1 for v in results.values() if v)
    total = 5
    xp_day = sum(XP_TABLE.get(k, 10) for k, v in results.items() if v)

    # Update streak
    async with aiosqlite.connect(DB_PATH) as db:
        streak = user["streak"]
        last = user["last_active"]

        if done_count == total:
            # Perfect day
            if last == yesterday:
                streak += 1
            elif last != today:
                streak = 1
        else:
            # Incomplete day — break streak
            old_streak = streak
            streak = 0
            if old_streak > 0:
                await query.message.reply_text(fail_message(old_streak))

        best = max(user["best_streak"], streak)
        mode = "tailung" if streak >= 30 else "normal"
        await db.execute(
            "UPDATE user SET streak=?, best_streak=?, last_active=?, mode=? WHERE user_id=?",
            (streak, best, today, mode, uid)
        )
        await db.commit()
        user = await get_user(db, uid)

    level = get_level(user["xp"])
    emoji_map = {"run":"🏃","reading":"📖","project":"💻","nutrition":"🥗","meditation":"🧘"}
    task_lines = []
    for k, label in [("run","Бег"),("reading","Чтение"),("project","Проект"),("nutrition","Питание"),("meditation","Медитация")]:
        tick = "✅" if results.get(k) else "❌"
        task_lines.append(f"{tick} {emoji_map[k]} {label}")

    streak_note = streak_message(streak) or ""
    perf = "💯 Идеальный день!" if done_count == total else f"⚠️ {done_count}/{total} задач"

    summary = (
        f"📊 *Итог дня — {today}*\n"
        f"{perf}\n\n"
        + "\n".join(task_lines) +
        f"\n\n+{xp_day} XP → {level}\n"
        f"🔥 Стрик: {streak} дней\n"
        + (f"\n{streak_note}" if streak_note else "") +
        "\n\nЗавтра в 7:00 — следующее задание."
    )

    await query.message.reply_text(summary, parse_mode="Markdown")

evening_handler = CommandHandler("evening", cmd_evening)
evening_cb_handler = CallbackQueryHandler(evening_callback, pattern="^ev_")