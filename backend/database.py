# ===============================
# БАЗА ДАННЫХ — двухрежимная
# Есть DATABASE_URL (Render + Neon)  -> PostgreSQL
# Нет DATABASE_URL (локальная разработка) -> SQLite, как раньше
# ===============================
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()  # чтобы DATABASE_URL можно было положить и в .env

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
USE_POSTGRES = DATABASE_URL.startswith("postgres")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    DBError = psycopg2.Error          # для обработчика ошибок в main.py
else:
    DBError = sqlite3.Error

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'trained.db')


class PgConnection:
    """
    Обёртка над psycopg2-соединением, которая ведёт себя как sqlite3:
    - conn.execute("SELECT ... WHERE x = ?", (v,)) — плейсхолдеры ? конвертируются в %s
    - строки результата — словари (row["col"] и dict(row) работают)
    - commit / rollback / close — как у sqlite
    Благодаря этому весь код в main.py работает без изменений.
    """
    def __init__(self, dsn):
        self._conn = psycopg2.connect(dsn)

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), params)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_connection():
    """Подключение к базе — Postgres в облаке, SQLite локально."""
    if USE_POSTGRES:
        return PgConnection(DATABASE_URL)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column_sqlite(conn, table, column, decl):
    """Мягкая миграция для SQLite: добавить колонку, если её нет."""
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    """Создание всех таблиц при первом запуске (в обоих режимах)."""
    conn = get_connection()

    # авто-инкрементный первичный ключ пишется по-разному
    pk = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

    tables = [
        f"""CREATE TABLE IF NOT EXISTS users (
            id {pk},
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE IF NOT EXISTS profile (
            id {pk},
            user_id INTEGER,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            height REAL,
            weight REAL,
            goal TEXT,
            experience TEXT,
            activity_level TEXT,
            injuries TEXT,
            pullups_max INTEGER DEFAULT 0,
            bench_max REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE IF NOT EXISTS training_log (
            id {pk},
            user_id INTEGER,
            day INTEGER,
            sleep_hours REAL,
            fatigue INTEGER,
            weight REAL,
            notes TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE IF NOT EXISTS nutrition_log (
            id {pk},
            user_id INTEGER,
            date TEXT,
            calories REAL,
            protein REAL,
            fat REAL,
            carbs REAL,
            water REAL DEFAULT 0,
            notes TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE IF NOT EXISTS chat_history (
            id {pk},
            user_id INTEGER,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        f"""CREATE TABLE IF NOT EXISTS workout_log (
            id {pk},
            user_id INTEGER,
            date TEXT,
            exercise_id TEXT,
            exercise_name TEXT,
            type TEXT,
            sets INTEGER,
            reps INTEGER,
            weight REAL DEFAULT 0,
            notes TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
    ]

    for t in tables:
        conn.execute(t)

    # мягкая миграция user_id для старых баз
    data_tables = ["profile", "training_log", "nutrition_log", "chat_history", "workout_log"]
    if USE_POSTGRES:
        for t in data_tables:
            conn.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS user_id INTEGER")
    else:
        for t in data_tables:
            _ensure_column_sqlite(conn, t, "user_id", "INTEGER")

    conn.commit()
    conn.close()
    print(f"✅ База данных инициализирована ({'PostgreSQL/Neon' if USE_POSTGRES else 'SQLite локально'})")


if __name__ == "__main__":
    init_db() 