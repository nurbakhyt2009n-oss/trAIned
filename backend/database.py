import sqlite3
import os

# База данных будет в корне проекта
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'trained.db')

def get_connection():
    """Подключение к базе данных"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # чтобы результаты были как словари
    return conn

def init_db():
    """Создание всех таблиц при первом запуске"""
    conn = get_connection()
    cursor = conn.cursor()

    # ===============================
    # ТАБЛИЦА: ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    # ТАБЛИЦА: ДНЕВНИК (сон/усталость/вес)
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS training_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day INTEGER,
            sleep_hours REAL,
            fatigue INTEGER,
            weight REAL,
            notes TEXT,
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===============================
    # ТАБЛИЦА: ПИТАНИЕ ЗА ДЕНЬ
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nutrition_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    # ТАБЛИЦА: ИСТОРИЯ ЧАТА С AI
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ===============================
    # ТАБЛИЦА: ЖУРНАЛ ТРЕНИРОВОК (упражнения/подходы/веса)
    # Каждая строка — одно упражнение в один день: подходы × повторы × вес.
    # ===============================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workout_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

# Запускаем создание таблиц при импорте
if __name__ == "__main__":
    init_db()
    print("Таблицы созданы:")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()

    for table in tables:
        print(f"  - {table['name']}")

    conn.close()