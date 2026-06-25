from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import aiosqlite
from database import DB_PATH, ensure_user

# Преднастроенные проекты Хару
DEFAULT_PROJECTS = [
    ("Impulse",     "💘", "пользователей", 47,    10000),
    ("Uzum Bot",    "🛒", "клиентов",      0,     50),
    ("Ресторан бот","🍽️", "клиентов",      0,     20),
]


async def _seed_projects(db, uid: int):
    """Вставить дефолтные проекты если их нет"""
    async with db.execute("SELECT COUNT(*) FROM project WHERE user_id=?", (uid,)) as cur:
        count = (await cur.fetchone())[0]
    if count == 0:
        for name, emoji, metric, val, target in DEFAULT_PROJECTS:
            await db.execute(
                "INSERT INTO project (user_id, name, emoji, metric_name, metric_val, target) "
                "VALUES (?,?,?,?,?,?)",
                (uid, name, emoji, metric, val, target)
            )
        await db.commit()


def _progress_bar(val: int, target: int, width: int = 10) -> str:
    pct = min(val / target, 1.0) if target else 0
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled)


async def cmd_projects(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        await ensure_user(db, uid)
        await _seed_projects(db, uid)
        async with db.execute(
            "SELECT id, name, emoji, metric_name, metric_val, target, status "
            "FROM project WHERE user_id=? ORDER BY id",
            (uid,)
        ) as cur:
            projects = await cur.fetchall()

    if not projects:
        await update.message.reply_text("Проектов нет. /add\_project Название Цель")
        return

    lines = ["🚀 *Твои проекты:*\n"]
    keyboard_rows = []

    for pid, name, emoji, metric, val, target, status in projects:
        pct = int(val / target * 100) if target else 0
        bar = _progress_bar(val, target)
        status_icon = "✅" if status == "done" else ("⏸" if status == "paused" else "🔄")
        lines.append(
            f"{status_icon} {emoji} *{name}*\n"
            f"`{bar}` {pct}%\n"
            f"{val:,} / {target:,} {metric}\n"
        )
        keyboard_rows.append([
            InlineKeyboardButton(f"📈 {name}", callback_data=f"proj_detail_{pid}"),
            InlineKeyboardButton("➕ Обновить", callback_data=f"proj_update_{pid}"),
        ])

    keyboard_rows.append([InlineKeyboardButton("➕ Новый проект", callback_data="proj_new")])

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard_rows)
    )


async def cmd_add_project(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /add_project Название Цель
    /add_project Impulse 10000
    """
    uid = update.effective_user.id
    args = ctx.args

    if len(args) < 2:
        await update.message.reply_text(
            "Формат: `/add_project Название Цель`\n"
            "Пример: `/add_project Impulse 10000`",
            parse_mode="Markdown"
        )
        return

    try:
        target = int(args[-1])
        name = " ".join(args[:-1])
    except ValueError:
        await update.message.reply_text("Последний аргумент должен быть числом — цель.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await ensure_user(db, uid)
        await db.execute(
            "INSERT INTO project (user_id, name, metric_val, target) VALUES (?,?,0,?)",
            (uid, name, target)
        )
        await db.commit()

    await update.message.reply_text(
        f"✅ Проект *{name}* добавлен. Цель: {target:,}\n"
        f"Обновляй метрику через /update\_project",
        parse_mode="Markdown"
    )


async def cmd_update_project(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /update_project — показать список для выбора
    /update_project 1 150 — обновить проект с id=1 до значения 150
    """
    uid = update.effective_user.id
    args = ctx.args

    async with aiosqlite.connect(DB_PATH) as db:
        await ensure_user(db, uid)
        await _seed_projects(db, uid)
        async with db.execute(
            "SELECT id, name, emoji, metric_val, target FROM project WHERE user_id=? AND status='active'",
            (uid,)
        ) as cur:
            projects = await cur.fetchall()

    if not projects:
        await update.message.reply_text("Нет активных проектов.")
        return

    # Если переданы аргументы — сразу обновляем
    if len(args) == 2:
        try:
            pid = int(args[0])
            new_val = int(args[1])
        except ValueError:
            await update.message.reply_text("Формат: `/update_project ID значение`", parse_mode="Markdown")
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT name, metric_val, target FROM project WHERE id=? AND user_id=?",
                (pid, uid)
            ) as cur:
                row = await cur.fetchone()

            if not row:
                await update.message.reply_text("Проект не найден.")
                return

            name, old_val, target = row
            delta = new_val - old_val
            await db.execute("UPDATE project SET metric_val=? WHERE id=?", (new_val, pid))
            await db.commit()

        pct = int(new_val / target * 100) if target else 0
        bar = _progress_bar(new_val, target)
        delta_str = f"(+{delta})" if delta > 0 else f"({delta})"

        await update.message.reply_text(
            f"📊 *{name}* обновлён\n"
            f"{old_val:,} → {new_val:,} {delta_str}\n"
            f"`{bar}` {pct}%",
            parse_mode="Markdown"
        )
        return

    # Иначе показываем кнопки
    keyboard = []
    for pid, name, emoji, val, target in projects:
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {name}: {val:,}/{target:,}",
            callback_data=f"proj_update_{pid}"
        )])

    await update.message.reply_text(
        "Выбери проект для обновления:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def project_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data == "proj_new":
        await query.message.reply_text(
            "Добавь проект: `/add_project Название Цель`\n"
            "Пример: `/add_project Uzum Bot 50`",
            parse_mode="Markdown"
        )
        return

    if data.startswith("proj_detail_"):
        pid = int(data.split("_")[-1])
        await _show_project_detail(query, uid, pid)
        return

    if data.startswith("proj_update_"):
        pid = int(data.split("_")[-1])
        ctx.user_data["awaiting_proj_update"] = pid
        await query.message.reply_text(
            f"Введи новое значение метрики для проекта #{pid}:\n"
            f"(просто число, например: `1250`)",
            parse_mode="Markdown"
        )
        return


async def _show_project_detail(query, uid: int, pid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, emoji, metric_name, metric_val, target, status FROM project WHERE id=? AND user_id=?",
            (pid, uid)
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await query.message.reply_text("Проект не найден.")
        return

    name, emoji, metric, val, target, status = row
    pct = int(val / target * 100) if target else 0
    bar = _progress_bar(val, target, width=15)
    remaining = target - val

    # Дней до конца лета (1 сентября)
    from datetime import date
    today = date.today()
    end_summer = date(today.year, 9, 1)
    days_left = (end_summer - today).days
    per_day = remaining / days_left if days_left > 0 else 0

    text = (
        f"{emoji} *{name}*\n\n"
        f"`{bar}` {pct}%\n\n"
        f"📊 Сейчас: {val:,}\n"
        f"🎯 Цель: {target:,} {metric}\n"
        f"📉 Осталось: {remaining:,}\n\n"
        f"⏳ До конца лета: {days_left} дней\n"
        f"📈 Нужно в день: ~{per_day:.0f} {metric}"
    )

    await query.message.reply_text(text, parse_mode="Markdown")


# Handlers
add_project_handler = CommandHandler("add_project", cmd_add_project)
list_projects_handler = CommandHandler("projects", cmd_projects)
update_project_handler = CommandHandler("update_project", cmd_update_project)
project_cb_handler = CallbackQueryHandler(project_callback, pattern="^proj_")