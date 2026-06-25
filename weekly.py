from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
import aiosqlite
from datetime import date, timedelta
from database import DB_PATH, ensure_user, get_user
from phrases import get_level, XP_TABLE

# Состояния диалога
Q1, Q2, Q3, Q4, Q5 = range(5)

QUESTIONS = [
    ("Q1 — Победы недели", "✅ Что ты сделал на этой неделе? Что получилось?"),
    ("Q2 — Провалы", "❌ Что не сделал? Что откладывал?"),
    ("Q3 — Причина", "🔍 Почему не сделал? Честно."),
    ("Q4 — Фокус следующей недели", "🎯 Какая главная задача на следующую неделю?"),
    ("Q5 — Что меняешь", "⚙️ Что конкретно меняешь в системе/привычках?"),
]

SHIFU_REACTIONS = {
    "positive": [
        "Слышу. Продолжай в том же духе — и не расслабляйся.",
        "Хорошо. Это только начало.",
        "Фиксирую. Завтра планка выше.",
    ],
    "negative": [
        "Значит, причина найдена. Устрани её до следующего воскресенья.",
        "Честность — это первый шаг. Второй — изменение.",
        "Отговорки закончились. Система работает только если ты работаешь.",
    ]
}

import random


async def cmd_weekly(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        user = await ensure_user(db, uid)

    # Статистика за неделю
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT task_key, COUNT(*) as cnt FROM daily_log "
            "WHERE user_id=? AND date>=? AND done=1 GROUP BY task_key",
            (uid, week_start)
        ) as cur:
            week_stats = dict(await cur.fetchall())

        async with db.execute(
            "SELECT id, name, emoji, metric_val, target FROM project WHERE user_id=? AND status='active'",
            (uid,)
        ) as cur:
            projects = await cur.fetchall()

    # Отчёт по неделе
    total_tasks = sum(week_stats.values())
    run_days = week_stats.get("run", 0)
    read_days = week_stats.get("reading", 0)
    proj_days = week_stats.get("project", 0)

    proj_lines = []
    for pid, name, emoji, val, target in projects:
        pct = int(val / target * 100) if target else 0
        proj_lines.append(f"{emoji} {name}: {val:,}/{target:,} ({pct}%)")

    summary = (
        f"📊 *Итог недели*\n\n"
        f"🏃 Пробежек: {run_days}/7\n"
        f"📖 Дней чтения: {read_days}/7\n"
        f"💻 Дней работы над проектами: {proj_days}/7\n"
        f"⚡ Всего задач выполнено: {total_tasks}\n\n"
    )

    if proj_lines:
        summary += "🚀 *Проекты:*\n" + "\n".join(proj_lines) + "\n\n"

    summary += "━━━━━━━━━━━━━━━\n*Время ревью. Отвечай честно.*\n\n"
    summary += f"1️⃣ {QUESTIONS[0][1]}"

    await update.message.reply_text(summary, parse_mode="Markdown")
    ctx.user_data["weekly_answers"] = []
    ctx.user_data["weekly_q"] = 0
    return Q1


async def weekly_q_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Принимает ответ и задаёт следующий вопрос"""
    text = update.message.text
    q_idx = ctx.user_data.get("weekly_q", 0)
    answers = ctx.user_data.get("weekly_answers", [])
    answers.append(text)
    ctx.user_data["weekly_answers"] = answers

    # Реакция Шифу
    reaction_type = "negative" if q_idx in [1, 2] else "positive"
    reaction = random.choice(SHIFU_REACTIONS[reaction_type])

    next_q = q_idx + 1
    ctx.user_data["weekly_q"] = next_q

    if next_q >= len(QUESTIONS):
        # Всё — завершаем
        await _finish_weekly(update, ctx)
        return ConversationHandler.END

    next_question = QUESTIONS[next_q][1]
    await update.message.reply_text(
        f"_{reaction}_\n\n{next_q + 1}️⃣ {next_question}",
        parse_mode="Markdown"
    )
    return next_q  # Q1..Q5 = 0..4


async def _finish_weekly(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    answers = ctx.user_data.get("weekly_answers", [])
    week = date.today().isocalendar()[1]

    async with aiosqlite.connect(DB_PATH) as db:
        # Сохраняем ревью
        await db.execute(
            "INSERT INTO weekly_review (user_id, week, done_good, done_bad, why_fail, next_focus, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (uid, week,
             answers[0] if len(answers) > 0 else "",
             answers[1] if len(answers) > 1 else "",
             answers[2] if len(answers) > 2 else "",
             answers[3] if len(answers) > 3 else "",
             date.today().isoformat())
        )

        # XP за ревью
        await db.execute("UPDATE user SET xp=xp+? WHERE user_id=?", (XP_TABLE.get("review", 60), uid))
        user = await get_user(db, uid)
        await db.commit()

    # Прогрессия бега на следующую неделю
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT run_km FROM user WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        old_km = row[0] if row else 3.0
        new_km = round(old_km + 0.5, 1)
        await db.execute("UPDATE user SET run_km=? WHERE user_id=?", (new_km, uid))
        await db.commit()

    level = get_level(user["xp"])

    final = (
        f"🥋 *Ревью сохранено.*\n\n"
        f"+{XP_TABLE.get('review', 60)} XP → {level}\n\n"
        f"📋 *Фокус следующей недели:*\n_{answers[3] if len(answers) > 3 else '—'}_\n\n"
        f"🏃 Дистанция на следующей неделе: *{new_km} км*\n\n"
        f"Увидимся в воскресенье. Не облажайся."
    )

    await update.message.reply_text(final, parse_mode="Markdown")
    ctx.user_data.clear()


async def start_weekly_review(bot: Bot, uid: int):
    """Вызывается планировщиком в воскресенье"""
    await bot.send_message(
        chat_id=uid,
        text=(
            "🌙 *Воскресный разбор*\n\n"
            "Шифу ждёт отчёта. Запусти /weekly когда готов.\n"
            "Это займёт 5 минут. Зато следующая неделя будет чётче."
        ),
        parse_mode="Markdown"
    )


# ConversationHandler для последовательных вопросов
weekly_conv_handler = ConversationHandler(
    entry_points=[CommandHandler("weekly", cmd_weekly)],
    states={
        Q1: [MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_q_handler)],
        Q2: [MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_q_handler)],
        Q3: [MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_q_handler)],
        Q4: [MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_q_handler)],
        Q5: [MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_q_handler)],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
    allow_reentry=True
)

# Экспортируем под теми именами, которые ждёт main.py
weekly_handler = weekly_conv_handler
weekly_cb_handler = CallbackQueryHandler(lambda u, c: None, pattern="^weekly_NONE$")