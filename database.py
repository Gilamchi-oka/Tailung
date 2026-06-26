import os
import aiosqlite
from typing import Optional

DATABASE_URL = os.getenv("DATABASE_URL")  # Railway Postgres URL (автоматически добавляется, если подключите плагин Postgres)
DB_PATH = os.getenv("DB_PATH", "shifu.db")  # локальный fallback для разработки

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS "user" (
    user_id BIGINT PRIMARY KEY,
    name TEXT DEFAULT 'Хару',
    xp INTEGER DEFAULT 0,
    streak INTEGER DEFAULT 0,
    best_streak INTEGER DEFAULT 0,
    run_km REAL DEFAULT 3.0,
    week_num INTEGER DEFAULT 0,
    last_active TEXT,
    mode TEXT DEFAULT 'normal'
);

CREATE TABLE IF NOT EXISTS daily_log (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    date TEXT,
    task_key TEXT,
    done INTEGER DEFAULT 0,
    value TEXT,
    proof_file TEXT
);

CREATE TABLE IF NOT EXISTS project (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    name TEXT,
    emoji TEXT DEFAULT '🚀',
    metric_name TEXT DEFAULT 'пользователей',
    metric_val INTEGER DEFAULT 0,
    target INTEGER DEFAULT 10000,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS book (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    title TEXT,
    pages_total INTEGER DEFAULT 0,
    pages_done INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS finance (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    date TEXT,
    amount REAL,
    category TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS weekly_review (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    week INTEGER,
    done_good TEXT,
    done_bad TEXT,
    why_fail TEXT,
    next_focus TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS challenge (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    date TEXT,
    text TEXT,
    done INTEGER DEFAULT 0
);
"""

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    user_id     INTEGER PRIMARY KEY,
    name        TEXT DEFAULT 'Хару',
    xp          INTEGER DEFAULT 0,
    streak      INTEGER DEFAULT 0,
    best_streak INTEGER DEFAULT 0,
    run_km      REAL DEFAULT 3.0,
    week_num    INTEGER DEFAULT 0,
    last_active TEXT,
    mode        TEXT DEFAULT 'normal'
);

CREATE TABLE IF NOT EXISTS daily_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    date        TEXT,
    task_key    TEXT,
    done        INTEGER DEFAULT 0,
    value       TEXT,
    proof_file  TEXT
);

CREATE TABLE IF NOT EXISTS project (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    name        TEXT,
    emoji       TEXT DEFAULT '🚀',
    metric_name TEXT DEFAULT 'пользователей',
    metric_val  INTEGER DEFAULT 0,
    target      INTEGER DEFAULT 10000,
    status      TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS book (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    title       TEXT,
    pages_total INTEGER DEFAULT 0,
    pages_done  INTEGER DEFAULT 0,
    active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS finance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    date        TEXT,
    amount      REAL,
    category    TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS weekly_review (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    week        INTEGER,
    done_good   TEXT,
    done_bad    TEXT,
    why_fail    TEXT,
    next_focus  TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS challenge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    date        TEXT,
    text        TEXT,
    done        INTEGER DEFAULT 0
);
"""


async def init_db() -> None:
    """
    Создаёт таблицы в Postgres (если DATABASE_URL задан) или в sqlite (файл DB_PATH).
    main.py вызывает init_db() при старте, поэтому отдельные миграции не нужны.
    """
    if DATABASE_URL:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            await conn.execute(POSTGRES_SCHEMA)
        finally:
            await conn.close()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executescript(SQLITE_SCHEMA)
            await db.commit()


async def get_user(db, user_id: int) -> Optional[dict]:
    """
    Возвращает словарь пользователя или None.
    Если DATABASE_URL задан — используем asyncpg и игнорируем переданный db.
    Если sqlite и db передан (aiosqlite.Connection) — используем его; иначе откроем своё соединение.
    """
    if DATABASE_URL:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            row = await conn.fetchrow('SELECT * FROM "user" WHERE user_id=$1', user_id)
            return dict(row) if row else None
        finally:
            await conn.close()
    else:
        if db is not None:
            async with db.execute("SELECT * FROM user WHERE user_id=?", (user_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))
        else:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute("SELECT * FROM user WHERE user_id=?", (user_id,)) as cur:
                    row = await cur.fetchone()
                    if not row:
                        return None
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))


async def ensure_user(db, user_id: int, name: str = "Хару") -> dict:
    """
    Убедиться, что пользователь есть; если нет — создать. Возвращает словарь пользователя.
    Поведение аналогично get_user в части выбора бэкенда.
    """
    if DATABASE_URL:
        import asyncpg
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            row = await conn.fetchrow('SELECT * FROM "user" WHERE user_id=$1', user_id)
            if not row:
                await conn.execute('INSERT INTO "user" (user_id, name) VALUES ($1, $2)', user_id, name)
                row = await conn.fetchrow('SELECT * FROM "user" WHERE user_id=$1', user_id)
            return dict(row)
        finally:
            await conn.close()
    else:
        if db is not None:
            async with db.execute("SELECT * FROM user WHERE user_id=?", (user_id,)) as cur:
                row = await cur.fetchone()
            if not row:
                await db.execute("INSERT INTO user (user_id, name) VALUES (?, ?)", (user_id, name))
                await db.commit()
                async with db.execute("SELECT * FROM user WHERE user_id=?", (user_id,)) as cur2:
                    row2 = await cur2.fetchone()
                    cols = [d[0] for d in cur2.description]
                    return dict(zip(cols, row2))
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))
        else:
            async with aiosqlite.connect(DB_PATH) as conn:
                async with conn.execute("SELECT * FROM user WHERE user_id=?", (user_id,)) as cur:
                    row = await cur.fetchone()
                if not row:
                    await conn.execute("INSERT INTO user (user_id, name) VALUES (?, ?)", (user_id, name))
                    await conn.commit()
                    async with conn.execute("SELECT * FROM user WHERE user_id=?", (user_id,)) as cur2:
                        row2 = await cur2.fetchone()
                        cols = [d[0] for d in cur2.description]
                        return dict(zip(cols, row2))
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))
