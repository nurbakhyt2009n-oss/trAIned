import sqlite3
import os

# База данных будет в корне проекта
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'trained.db')

def get_connection():
    """Подключение к базе данных"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _ensure_column(cursor, table, column, decl):
    """Мягкая миграция: добавить колонку, если её ещё нет (для старых баз)."""
    cols = [r["name"] for r in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

def init_db():
    """Создание всех таблиц при первом запуске"""
    conn = get_connection()
    cursor = conn.cursor()

    # ===============================
    # ПОЛЬЗОВАТЕЛИ И СЕССИИ (мультипользовательский режим)
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===============================
    # ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        )
    """)

    # ===============================
    # ДНЕВНИК (сон/усталость/вес)
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS training_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            day INTEGER,
            sleep_hours REAL,
            fatigue INTEGER,
            weight REAL,
            notes TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===============================
    # ПИТАНИЕ ЗА ДЕНЬ
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nutrition_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            calories REAL,
            protein REAL,
            fat REAL,
            carbs REAL,
            water REAL DEFAULT 0,
            notes TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===============================
    # ИСТОРИЯ ЧАТА С AI
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===============================
    # ЖУРНАЛ ТРЕНИРОВОК (упражнения/подходы/веса)
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workout_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        )
    """)

    # Мягкая миграция старых баз: добавляем user_id, если таблицы были без него
    for t in ["profile", "training_log", "nutrition_log", "chat_history", "workout_log"]:
        _ensure_column(cursor, t, "user_id", "INTEGER")

    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

if __name__ == "__main__":
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    for table in cursor.fetchall():
        print(f"  - {table['name']}")
    conn.close()