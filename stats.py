from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler
import aiosqlite
from datetime import date, timedelta
from database import DB_PATH, ensure_user, get_user
from phrases import get_level


def _bar(val: int, target: int, width: int = 12) -> str:
    pct = min(val / target, 1.0) if target else 0
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        user = await ensure_user(db, uid)

        # Проекты
        async with db.execute(
            "SELECT name, emoji, metric_name, metric_val, target FROM project "
            "WHERE user_id=? AND status='active' ORDER BY id",
            (uid,)
        ) as cur:
            projects = await cur.fetchall()

        # Книга
        async with db.execute(
            "SELECT title, pages_done, pages_total FROM book WHERE user_id=? AND active=1",
            (uid,)
        ) as cur:
            book = await cur.fetchone()

        # Статистика за последние 7 дней
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        async with db.execute(
            "SELECT task_key, COUNT(*) FROM daily_log "
            "WHERE user_id=? AND date>? AND done=1 GROUP BY task_key",
            (uid, week_ago)
        ) as cur:
            week_stats = dict(await cur.fetchall())

        # Последнее ревью
        async with db.execute(
            "SELECT next_focus FROM weekly_review WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (uid,)
        ) as cur:
            review = await cur.fetchone()

    level = get_level(user["xp"])

    # Дней до конца лета
    today = date.today()
    end_summer = date(today.year, 9, 1)
    days_left = (end_summer - today).days

    lines = [
        f"📊 *Дашборд — {user['name']}*",
        f"",
        f"{level} | ⚡ {user['xp']} XP",
        f"🔥 Стрик: *{user['streak']} дней* (рекорд: {user['best_streak']})",
        f"🏃 Дистанция: {user['run_km']} км/день",
        f"",
        f"━━━━━━━━━━━━━━━━",
        f"📅 *Неделя (7 дней):*",
        f"🏃 Пробежек: {week_stats.get('run', 0)}/7",
        f"📖 Чтения: {week_stats.get('reading', 0)}/7",
        f"💻 Проектов: {week_stats.get('project', 0)}/7",
        f"🧘 Медитаций: {week_stats.get('meditation', 0)}/7",
        f"",
        f"━━━━━━━━━━━━━━━━",
        f"🚀 *Проекты (до конца лета: {days_left} дн.):*",
    ]

    if projects:
        for name, emoji, metric, val, target in projects:
            pct = int(val / target * 100) if target else 0
            bar = _bar(val, target)
            remaining = target - val
            per_day = remaining / days_left if days_left > 0 else 0
            lines.append(
                f"\n{emoji} *{name}*\n"
                f"`{bar}` {pct}%\n"
                f"{val:,} / {target:,} {metric}\n"
                f"Нужно в день: ~{per_day:.1f}"
            )
    else:
        lines.append("_Нет проектов. /add\_project_")

    if book:
        title, done, total = book
        pct = int(done / total * 100) if total else 0
        bar = _bar(done, total)
        lines += [
            f"",
            f"━━━━━━━━━━━━━━━━",
            f"📖 *Книга:* {title}",
            f"`{bar}` {pct}% ({done}/{total} стр.)",
        ]

    if review:
        lines += [
            f"",
            f"━━━━━━━━━━━━━━━━",
            f"🎯 *Фокус недели:*",
            f"_{review[0]}_",
        ]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Проекты", callback_data="proj_list"),
            InlineKeyboardButton("📖 Книга", callback_data="book_status"),
        ],
        [InlineKeyboardButton("📋 Утреннее задание", callback_data="go_morning")],
    ])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=keyboard
    )


stats_handler = CommandHandler("stats", cmd_stats)