from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import aiosqlite
from datetime import date
from database import DB_PATH, ensure_user


async def cmd_add_book(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /add_book Название книги 320
    Последний аргумент — количество страниц
    """
    uid = update.effective_user.id
    args = ctx.args

    if len(args) < 2:
        await update.message.reply_text(
            "Формат: `/add_book Название Страниц`\n"
            "Пример: `/add_book Атомные привычки 320`",
            parse_mode="Markdown"
        )
        return

    try:
        pages = int(args[-1])
        title = " ".join(args[:-1])
    except ValueError:
        await update.message.reply_text("Последний аргумент — число страниц.")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await ensure_user(db, uid)
        # Деактивируем предыдущую книгу
        await db.execute("UPDATE book SET active=0 WHERE user_id=?", (uid,))
        await db.execute(
            "INSERT INTO book (user_id, title, pages_total, pages_done, active) VALUES (?,?,?,0,1)",
            (uid, title, pages)
        )
        await db.commit()

    await update.message.reply_text(
        f"📖 Книга добавлена: *{title}*\n"
        f"Всего страниц: {pages}\n\n"
        f"Обновляй прогресс: `/book_progress 30`",
        parse_mode="Markdown"
    )


async def cmd_book_progress(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /book_progress 45   — прочитал ещё 45 страниц сегодня
    /book_progress =150 — сейчас на странице 150 (абсолютное)
    """
    uid = update.effective_user.id
    args = ctx.args

    if not args:
        await _show_book_status(update, uid)
        return

    raw = args[0]
    absolute = raw.startswith("=")
    try:
        val = int(raw.lstrip("="))
    except ValueError:
        await update.message.reply_text("Пример: `/book_progress 30` или `/book_progress =150`", parse_mode="Markdown")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await ensure_user(db, uid)
        async with db.execute(
            "SELECT id, title, pages_done, pages_total FROM book WHERE user_id=? AND active=1",
            (uid,)
        ) as cur:
            book = await cur.fetchone()

        if not book:
            await update.message.reply_text("Нет активной книги. /add\_book Название Страниц", parse_mode="Markdown")
            return

        bid, title, done, total = book

        if absolute:
            new_done = min(val, total)
        else:
            new_done = min(done + val, total)

        await db.execute("UPDATE book SET pages_done=? WHERE id=?", (new_done, bid))

        # Лог чтения за сегодня
        today = date.today().isoformat()
        pages_today = new_done - done
        if pages_today > 0:
            await db.execute(
                "INSERT OR REPLACE INTO daily_log (user_id, date, task_key, done, value) VALUES (?,?,?,1,?)",
                (uid, today, "reading", str(pages_today))
            )

        await db.commit()

    pct = int(new_done / total * 100) if total else 0
    bar_filled = pct // 5
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    pages_left = total - new_done
    days_to_finish = round(pages_left / 30) if pages_left > 0 else 0

    if new_done >= total:
        msg = (
            f"🎉 *«{title}» — ПРОЧИТАНА!*\n\n"
            f"Отличная работа. Добавь следующую: /add\_book"
        )
    else:
        msg = (
            f"📖 *{title}*\n"
            f"`{bar}` {pct}%\n\n"
            f"Страница {new_done} из {total}\n"
            f"Осталось: {pages_left} стр. (~{days_to_finish} дней по 30/день)"
        )

    await update.message.reply_text(msg, parse_mode="Markdown")


async def _show_book_status(update: Update, uid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT title, pages_done, pages_total FROM book WHERE user_id=? AND active=1",
            (uid,)
        ) as cur:
            book = await cur.fetchone()

    if not book:
        await update.message.reply_text("Нет активной книги. /add\_book Название Страниц", parse_mode="Markdown")
        return

    title, done, total = book
    pct = int(done / total * 100) if total else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)

    await update.message.reply_text(
        f"📖 *{title}*\n"
        f"`{bar}` {pct}%\n"
        f"Страница {done} из {total}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📄 +10 страниц", callback_data="book_+10"),
            InlineKeyboardButton("📄 +30 страниц", callback_data="book_+30"),
        ]])
    )


async def book_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data.startswith("book_+"):
        pages = int(query.data.split("+")[1])
        today = date.today().isoformat()

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id, pages_done, pages_total, title FROM book WHERE user_id=? AND active=1",
                (uid,)
            ) as cur:
                book = await cur.fetchone()

            if not book:
                await query.message.reply_text("Нет активной книги.")
                return

            bid, done, total, title = book
            new_done = min(done + pages, total)
            await db.execute("UPDATE book SET pages_done=? WHERE id=?", (new_done, bid))
            await db.execute(
                "INSERT OR REPLACE INTO daily_log (user_id, date, task_key, done, value) VALUES (?,?,?,1,?)",
                (uid, today, "reading", str(pages))
            )
            await db.commit()

        pct = int(new_done / total * 100) if total else 0
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        await query.edit_message_text(
            f"📖 *{title}*\n"
            f"`{bar}` {pct}%\n"
            f"Страница {new_done} из {total} (+{pages})",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📄 +10 страниц", callback_data="book_+10"),
                InlineKeyboardButton("📄 +30 страниц", callback_data="book_+30"),
            ]])
        )


add_book_handler = CommandHandler("add_book", cmd_add_book)
book_progress_handler = CommandHandler("book_progress", cmd_book_progress)
book_cb_handler = CallbackQueryHandler(book_callback, pattern="^book_")
