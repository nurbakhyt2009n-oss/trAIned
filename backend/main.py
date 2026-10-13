# ===============================
# trAIned — FastAPI СЕРВЕР (API)
# v2.0 — мультипользовательский режим
# ===============================

import os
import json
import hashlib
import secrets
from contextlib import contextmanager
from datetime import date as _date
from typing import Optional, Literal

import io
import re
import time
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Header, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from backend.database import get_connection, init_db, DB_ERRORS
    from backend.calculations import get_full_nutrition_plan
    from backend.ai_coach import get_ai_response, generate_workout_plan, generate_meal_plan, analyze_food_photo, analyze_food_text
    from backend.exercises import get_exercise, get_grouped, suggest_progression
    from backend.program import generate_program, next_session
    from backend.stats import compute_stats, render_report_html, build_backup
except ImportError:
    from database import get_connection, init_db, DB_ERRORS
    from calculations import get_full_nutrition_plan
    from ai_coach import get_ai_response, generate_workout_plan, generate_meal_plan, analyze_food_photo, analyze_food_text
    from exercises import get_exercise, get_grouped, suggest_progression
    from program import generate_program, next_session
    from stats import compute_stats, render_report_html, build_backup


app = FastAPI(title="trAIned API", version="2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


# ===============================
# БЕЗОПАСНАЯ РАБОТА С БАЗОЙ
# ===============================
@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def db_error_handler(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Ошибка базы данных. Попробуй ещё раз."})

# регистрируем обработчик для ошибок и SQLite, и Postgres
for _exc in DB_ERRORS:
    app.add_exception_handler(_exc, db_error_handler)


# ===============================
# АВТОРИЗАЦИЯ
# Пароли: PBKDF2-SHA256, 600k итераций, соль (старые хэши 100k обновляются при входе).
# Сессии: в базе хранится только SHA-256 токена, срок жизни — SESSION_DAYS.
# Защита от подбора: лимит неудачных попыток входа и регистраций.
# ===============================
PBKDF2_ITERATIONS = 600_000
SESSION_DAYS = 30
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,30}$")
COMMON_PASSWORDS = {"12345678", "123456789", "1234567890", "password", "password1", "qwerty123",
                    "11111111", "qwertyui", "1q2w3e4r", "йцукенгш", "abc12345", "parol123"}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${h}"


def verify_password(password: str, stored: str):
    """-> (верный ли пароль, нужно ли пересчитать хэш по новым правилам)"""
    parts = (stored or "").split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        iterations, salt, expected = int(parts[1]), parts[2], parts[3]
    elif len(parts) == 2:                       # старый формат: salt$hash, 100k итераций
        iterations, salt, expected = 100_000, parts[0], parts[1]
    else:
        return False, False
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    ok = secrets.compare_digest(h, expected)
    return ok, ok and iterations < PBKDF2_ITERATIONS


_DUMMY_HASH = hash_password(secrets.token_hex(8))   # чтобы «нет такого логина» не отвечал быстрее


def password_problem(password: str, username: str):
    """Текст ошибки, если пароль слабый, иначе None."""
    if len(password) < 8:
        return "Пароль — минимум 8 символов"
    if len(password) > 128:
        return "Пароль слишком длинный"
    if not re.search(r"[A-Za-zА-Яа-яЁё]", password) or not re.search(r"\d", password):
        return "Пароль должен содержать буквы и цифры"
    if password.lower() in COMMON_PASSWORDS or password.lower() == username:
        return "Слишком простой пароль — придумай другой"
    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(conn, user_id) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (_token_hash(token), user_id))
    return token


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)[:19])
    except (TypeError, ValueError):
        return None


class RateLimiter:
    """Простой счётчик попыток в памяти: не больше `limit` событий за `window` секунд."""
    def __init__(self, limit, window):
        self.limit, self.window = limit, window
        self.hits = defaultdict(deque)

    def _prune(self, key):
        q, now = self.hits[key], time.monotonic()
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked_for(self, key):
        q = self._prune(key)
        if len(q) >= self.limit:
            return int(self.window - (time.monotonic() - q[0])) + 1
        return 0

    def hit(self, key):
        self._prune(key).append(time.monotonic())
        if len(self.hits) > 20_000:
            self.hits.clear()

    def reset(self, key):
        self.hits.pop(key, None)


login_fails_user = RateLimiter(limit=5, window=15 * 60)    # на логин + IP
login_fails_ip = RateLimiter(limit=50, window=15 * 60)     # на IP в целом (школа/общий Wi-Fi)
register_ip = RateLimiter(limit=20, window=60 * 60)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")      # Render стоит перед приложением как прокси
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _too_many(seconds):
    minutes = max(1, round(seconds / 60))
    raise HTTPException(status_code=429, detail=f"Слишком много попыток. Попробуй через {minutes} мин.")


_seen_today = set()   # (user_id, день) — чтобы писать визит в базу раз в день


def record_visit(conn, user_id):
    """Один ряд на пользователя в день — для статистики DAU/WAU и удержания."""
    today = _date.today().isoformat()
    if (user_id, today) in _seen_today:
        return
    exists = conn.execute(
        "SELECT 1 FROM user_visits WHERE user_id = ? AND day = ?", (user_id, today)
    ).fetchone()
    if not exists:
        conn.execute("INSERT INTO user_visits (user_id, day) VALUES (?, ?)", (user_id, today))
    if len(_seen_today) > 50_000:
        _seen_today.clear()
    _seen_today.add((user_id, today))


def get_current_user(authorization: str = Header(default="")) -> int:
    """Достаёт user_id из заголовка Authorization: Bearer <token>."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется вход")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Требуется вход")
    hashed = _token_hash(token)
    with get_db() as conn:
        row = conn.execute("SELECT user_id, created_at FROM sessions WHERE token = ?", (hashed,)).fetchone()
        if not row:
            # сессии, созданные до перехода на хэши: находим и сразу переписываем
            row = conn.execute("SELECT user_id, created_at FROM sessions WHERE token = ?", (token,)).fetchone()
            if row:
                conn.execute("UPDATE sessions SET token = ? WHERE token = ?", (hashed, token))
        if row:
            created = _as_datetime(row["created_at"])
            if created and created < datetime.utcnow() - timedelta(days=SESSION_DAYS):
                conn.execute("DELETE FROM sessions WHERE token = ?", (hashed,))
                row = None
        if row:
            try:
                record_visit(conn, row["user_id"])
            except DB_ERRORS:
                conn.rollback()   # статистика не должна ломать запрос
    if not row:
        raise HTTPException(status_code=401, detail="Сессия истекла — войди заново")
    return row["user_id"]


# ===============================
# МОДЕЛИ ДАННЫХ
# ===============================
Equipment = Literal["bodyweight", "dumbbells", "gym", "band"]


class AuthIn(BaseModel):
    # строгие правила проверяются вручную — чтобы ошибки были понятными и на русском
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    age: int = Field(ge=12, le=100)
    gender: Literal["male", "female"]
    height: float = Field(ge=120, le=230)
    weight: float = Field(ge=30, le=250)
    goal: Literal["muscle_gain", "fat_loss", "recomposition", "maintenance", "endurance"]
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"]
    experience: Literal["Beginner", "Intermediate", "Advanced", "Pro"] = "Intermediate"
    injuries: str = Field(default="нет", max_length=500)
    pullups_max: int = Field(default=0, ge=0, le=100)
    bench_max: float = Field(default=0, ge=0, le=400)
    days_per_week: Optional[int] = Field(default=None, ge=2, le=6)
    equipment: Optional[list[Equipment]] = Field(default=None, max_length=4)


class PlanSettingsIn(BaseModel):
    days_per_week: int = Field(ge=2, le=6)
    equipment: list[Equipment] = Field(min_length=1, max_length=4)
    experience: Optional[Literal["Beginner", "Intermediate", "Advanced", "Pro"]] = None


class DailyLogIn(BaseModel):
    sleep_hours: float = Field(ge=0, le=24)
    fatigue: int = Field(ge=1, le=10)
    weight: Optional[float] = Field(default=None, ge=30, le=250)
    notes: str = Field(default="", max_length=500)


class NutritionLogIn(BaseModel):
    calories: float = Field(ge=0, le=10000)
    protein: float = Field(ge=0, le=1000)
    fat: float = Field(ge=0, le=1000)
    carbs: float = Field(ge=0, le=2000)
    water: float = Field(default=0, ge=0, le=15)
    date: Optional[str] = None
    notes: str = Field(default="", max_length=500)


class MealPlanIn(BaseModel):
    preferences: str = Field(default="обычное питание", max_length=300)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class PhotoIn(BaseModel):
    image: str = Field(min_length=10, max_length=8_000_000)


class FoodTextIn(BaseModel):
    description: str = Field(min_length=2, max_length=500)


class ExerciseLogIn(BaseModel):
    exercise_id: str = Field(min_length=1, max_length=50)
    sets: int = Field(ge=1, le=20)
    reps: int = Field(ge=1, le=200)
    weight: float = Field(default=0, ge=0, le=500)
    date: Optional[str] = None
    notes: str = Field(default="", max_length=300)


# ===============================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (все — с user_id)
# ===============================
def get_profile(user_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM profile WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def get_latest_log(user_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM training_log WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def get_weekly_stats(user_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sleep_hours, fatigue FROM training_log WHERE user_id = ? ORDER BY id DESC LIMIT 7",
            (user_id,),
        ).fetchall()
    if not rows:
        return None
    sleeps = [r["sleep_hours"] for r in rows if r["sleep_hours"] is not None]
    fatigues = [r["fatigue"] for r in rows if r["fatigue"] is not None]
    return {
        "avg_sleep": round(sum(sleeps) / len(sleeps), 1) if sleeps else None,
        "avg_fatigue": round(sum(fatigues) / len(fatigues), 1) if fatigues else None,
        "days_logged": len(rows),
    }


def build_nutrition_plan(profile):
    if not profile:
        return None
    return get_full_nutrition_plan(
        weight=profile["weight"], height=profile["height"], age=profile["age"],
        gender=profile["gender"], activity_level=profile["activity_level"], goal=profile["goal"],
    )


def save_plan(user_id, profile):
    """Сгенерировать программу по профилю и сохранить (старая заменяется)."""
    plan = generate_program(profile)
    with get_db() as conn:
        conn.execute("DELETE FROM training_plan WHERE user_id = ?", (user_id,))
        conn.execute(
            "INSERT INTO training_plan (user_id, created_on, plan_json) VALUES (?, ?, ?)",
            (user_id, plan["generated_on"], json.dumps(plan, ensure_ascii=False)),
        )
    return plan


def load_plan(user_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT created_on, plan_json FROM training_plan WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if not row:
        return None, None
    return json.loads(row["plan_json"]), row["created_on"]


def plan_progress(user_id, plan, created_on):
    """Сколько тренировочных дней записано с момента создания плана -> следующая тренировка."""
    with get_db() as conn:
        done = conn.execute(
            "SELECT COUNT(DISTINCT date) AS c FROM workout_log WHERE user_id = ? AND date >= ?",
            (user_id, created_on),
        ).fetchone()["c"]
    return next_session(plan, done or 0)


def best_of(ex_type, rows):
    if not rows:
        return None
    if ex_type == "weight":
        top = max(rows, key=lambda r: (r["weight"] or 0, r["reps"] or 0))
    else:
        top = max(rows, key=lambda r: (r["reps"] or 0))
    return {"weight": top["weight"], "reps": top["reps"], "date": top["date"], "sets": top["sets"]}


# ===============================
# СЛУЖЕБНЫЕ
# ===============================
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "trAIned"}


@app.get("/api/stats")
def stats():
    """Публичная статистика приложения — сколько людей реально пользуется."""
    with get_db() as conn:
        users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        workouts = conn.execute("SELECT COUNT(*) AS c FROM workout_log").fetchone()["c"]
        meals = conn.execute("SELECT COUNT(*) AS c FROM nutrition_log").fetchone()["c"]
        checkins = conn.execute("SELECT COUNT(*) AS c FROM training_log").fetchone()["c"]
    return {"users": users, "workouts_logged": workouts, "meals_logged": meals, "checkins": checkins}


# ===============================
# АДМИН: статистика и бэкап (только с ADMIN_TOKEN)
# Если ADMIN_TOKEN не задан в окружении — эндпоинты просто не существуют (404).
# ===============================
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()


def require_admin(x_admin_token: str = Header(default=""), key: str = Query(default="")):
    if len(ADMIN_TOKEN) < 16:
        raise HTTPException(status_code=404, detail="Not Found")
    supplied = x_admin_token or key
    if not secrets.compare_digest(supplied.encode(), ADMIN_TOKEN.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/api/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats():
    with get_db() as conn:
        return compute_stats(conn)


@app.get("/api/admin/report", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def admin_report():
    with get_db() as conn:
        return render_report_html(compute_stats(conn))


@app.get("/api/admin/backup", dependencies=[Depends(require_admin)])
def admin_backup():
    with get_db() as conn:
        files, _ = build_backup(conn)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="trained-backup-{stamp}.zip"',
                             "Cache-Control": "no-store"})


# ===============================
# АВТОРИЗАЦИЯ: РЕГИСТРАЦИЯ / ВХОД / ВЫХОД
# ===============================
@app.post("/api/auth/register")
def register(body: AuthIn, request: Request):
    ip = client_ip(request)
    wait = register_ip.blocked_for(ip)
    if wait:
        _too_many(wait)
    username = body.username.strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400,
                            detail="Логин: 3–30 символов, латинские буквы, цифры, точка, _ или -")
    problem = password_problem(body.password, username)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    with get_db() as conn:
        exists = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="Такой логин уже занят")
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(body.password)),
        )
        user_id = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()["id"]
        token = create_session(conn, user_id)
    register_ip.hit(ip)
    return {"token": token, "username": username}


@app.post("/api/auth/login")
def login(body: AuthIn, request: Request):
    username = body.username.strip().lower()
    ip = client_ip(request)
    key = f"{ip}|{username}"
    wait = max(login_fails_user.blocked_for(key), login_fails_ip.blocked_for(ip))
    if wait:
        _too_many(wait)
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        ok, needs_rehash = verify_password(body.password, user["password_hash"] if user else _DUMMY_HASH)
        if not user or not ok:
            login_fails_user.hit(key)
            login_fails_ip.hit(ip)
            raise HTTPException(status_code=401, detail="Неверный логин или пароль")
        if needs_rehash:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (hash_password(body.password), user["id"]))
        # заодно чистим просроченные сессии этого пользователя
        cutoff = datetime.utcnow() - timedelta(days=SESSION_DAYS)
        for s_row in conn.execute("SELECT token, created_at FROM sessions WHERE user_id = ?",
                                  (user["id"],)).fetchall():
            created = _as_datetime(s_row["created_at"])
            if created and created < cutoff:
                conn.execute("DELETE FROM sessions WHERE token = ?", (s_row["token"],))
        token = create_session(conn, user["id"])
    login_fails_user.reset(key)
    return {"token": token, "username": username}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default="")):
    token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if token:
        with get_db() as conn:
            conn.execute("DELETE FROM sessions WHERE token IN (?, ?)", (_token_hash(token), token))
    return {"status": "logged_out"}


@app.post("/api/auth/logout-all")
def logout_all(user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return {"status": "logged_out_everywhere"}


@app.post("/api/auth/change-password")
def change_password(body: ChangePasswordIn, request: Request,
                    authorization: str = Header(default=""),
                    user_id: int = Depends(get_current_user)):
    key = f"{client_ip(request)}|change|{user_id}"
    wait = login_fails_user.blocked_for(key)
    if wait:
        _too_many(wait)
    with get_db() as conn:
        user = conn.execute("SELECT username, password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        ok, _ = verify_password(body.current_password, user["password_hash"])
        if not ok:
            login_fails_user.hit(key)
            raise HTTPException(status_code=400, detail="Текущий пароль неверный")
        problem = password_problem(body.new_password, user["username"])
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (hash_password(body.new_password), user_id))
        # выходим на всех остальных устройствах, текущая сессия остаётся
        current = _token_hash(authorization[7:].strip())
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND token <> ?", (user_id, current))
    return {"status": "password_changed"}


@app.get("/api/auth/me")
def me(user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    return {"username": row["username"] if row else None}


# ===============================
# ПРОФИЛЬ
# ===============================
@app.post("/api/profile")
def save_profile(p: ProfileIn, user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        old = conn.execute(
            "SELECT days_per_week, equipment FROM profile WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        # если в запросе нет настроек программы — сохраняем прежние
        days = p.days_per_week or (old["days_per_week"] if old else None)
        equipment = ",".join(p.equipment) if p.equipment else (old["equipment"] if old else None)
        conn.execute("DELETE FROM profile WHERE user_id = ?", (user_id,))
        conn.execute(
            """INSERT INTO profile
               (user_id, name, age, gender, height, weight, goal, experience,
                activity_level, injuries, pullups_max, bench_max, days_per_week, equipment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, p.name, p.age, p.gender, p.height, p.weight, p.goal, p.experience,
             p.activity_level, p.injuries, p.pullups_max, p.bench_max, days, equipment),
        )
    profile = get_profile(user_id)
    plan = save_plan(user_id, profile) if days and equipment else None
    return {"profile": profile, "nutrition_plan": build_nutrition_plan(profile),
            "training_plan": plan["summary"] if plan else None}


@app.get("/api/profile")
def read_profile(user_id: int = Depends(get_current_user)):
    profile = get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    return profile


# ===============================
# ПИТАНИЕ
# ===============================
@app.get("/api/nutrition/plan")
def nutrition_plan(user_id: int = Depends(get_current_user)):
    profile = get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Сначала заполни профиль")
    return build_nutrition_plan(profile)


@app.post("/api/nutrition/meal-plan")
def meal_plan(body: MealPlanIn, user_id: int = Depends(get_current_user)):
    profile = get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Сначала заполни профиль")
    return {"meal_plan": generate_meal_plan(build_nutrition_plan(profile), body.preferences)}


@app.post("/api/nutrition/analyze-photo")
def analyze_photo(body: PhotoIn, user_id: int = Depends(get_current_user)):
    result = analyze_food_photo(body.image)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail="Не удалось распознать фото. Попробуй другое фото.")
    return result["data"]


@app.post("/api/nutrition/analyze-text")
def analyze_text(body: FoodTextIn, user_id: int = Depends(get_current_user)):
    result = analyze_food_text(body.description)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail="Не удалось оценить. Попробуй описать иначе.")
    return result["data"]


@app.get("/api/nutrition/today")
def nutrition_today(user_id: int = Depends(get_current_user)):
    profile = get_profile(user_id)
    target = build_nutrition_plan(profile) if profile else None
    today = _date.today().isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM nutrition_log WHERE user_id = ? AND date = ? ORDER BY id ASC",
            (user_id, today),
        ).fetchall()
    entries = [dict(r) for r in rows]
    consumed = {
        "calories": round(sum(e["calories"] or 0 for e in entries)),
        "protein": round(sum(e["protein"] or 0 for e in entries)),
        "fat": round(sum(e["fat"] or 0 for e in entries)),
        "carbs": round(sum(e["carbs"] or 0 for e in entries)),
    }
    return {"date": today, "target": target, "consumed": consumed, "entries": entries}


@app.post("/api/nutrition/log")
def log_nutrition(body: NutritionLogIn, user_id: int = Depends(get_current_user)):
    d = body.date or _date.today().isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO nutrition_log (user_id, date, calories, protein, fat, carbs, water, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, d, body.calories, body.protein, body.fat, body.carbs, body.water, body.notes),
        )
    return {"status": "saved", "date": d}


@app.get("/api/nutrition/logs")
def nutrition_logs(user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM nutrition_log WHERE user_id = ? ORDER BY id ASC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/nutrition/log/{entry_id}")
def delete_nutrition_log(entry_id: int, user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        conn.execute("DELETE FROM nutrition_log WHERE id = ? AND user_id = ?", (entry_id, user_id))
    return {"status": "deleted"}


# ===============================
# ТРЕНИРОВКИ — дневник состояния
# ===============================
@app.post("/api/training/workout")
def workout(user_id: int = Depends(get_current_user)):
    profile = get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Сначала заполни профиль")
    plan, created_on = load_plan(user_id)
    planned = plan_progress(user_id, plan, created_on)["day"] if plan else None
    return {"workout": generate_workout_plan(profile, get_latest_log(user_id), planned)}


# ===============================
# ТРЕНИРОВКИ — программа на 4 недели
# ===============================
@app.get("/api/training/plan")
def training_plan(user_id: int = Depends(get_current_user)):
    profile = get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Сначала заполни профиль")
    plan, created_on = load_plan(user_id)
    if not plan:
        if not (profile.get("days_per_week") and profile.get("equipment")):
            # старые профили: нужно уточнить дни и инвентарь
            return {"needs_setup": True, "experience": profile.get("experience")}
        plan = save_plan(user_id, profile)
        created_on = plan["generated_on"]
    return {"needs_setup": False, "plan": plan, "created_on": created_on,
            "next": plan_progress(user_id, plan, created_on)}


@app.post("/api/training/plan")
def update_training_plan(body: PlanSettingsIn, user_id: int = Depends(get_current_user)):
    profile = get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Сначала заполни профиль")
    experience = body.experience or profile.get("experience")
    equipment = ",".join(body.equipment)
    with get_db() as conn:
        conn.execute(
            "UPDATE profile SET days_per_week = ?, equipment = ?, experience = ? WHERE id = ?",
            (body.days_per_week, equipment, experience, profile["id"]),
        )
    plan = save_plan(user_id, get_profile(user_id))
    return {"needs_setup": False, "plan": plan, "created_on": plan["generated_on"],
            "next": plan_progress(user_id, plan, plan["generated_on"])}


@app.post("/api/training/log")
def log_training(body: DailyLogIn, user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM training_log WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        day = count + 1
        conn.execute(
            """INSERT INTO training_log (user_id, day, sleep_hours, fatigue, weight, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, day, body.sleep_hours, body.fatigue, body.weight, body.notes),
        )
    return {"status": "saved", "day": day}


@app.get("/api/training/logs")
def training_logs(user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM training_log WHERE user_id = ? ORDER BY id ASC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ===============================
# ТРЕНИРОВКИ — журнал упражнений
# ===============================
@app.get("/api/exercises")
def exercises(user_id: int = Depends(get_current_user)):
    return get_grouped()


@app.post("/api/training/exercise-log")
def log_exercise(body: ExerciseLogIn, user_id: int = Depends(get_current_user)):
    ex = get_exercise(body.exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    d = body.date or _date.today().isoformat()
    with get_db() as conn:
        prior = conn.execute(
            "SELECT sets, reps, weight, date FROM workout_log WHERE exercise_id = ? AND user_id = ?",
            (body.exercise_id, user_id),
        ).fetchall()
        conn.execute(
            """INSERT INTO workout_log (user_id, date, exercise_id, exercise_name, type, sets, reps, weight, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, d, ex["id"], ex["name"], ex["type"], body.sets, body.reps, body.weight, body.notes),
        )
    prev_best = best_of(ex["type"], prior)
    is_pr = False
    if prev_best is None:
        is_pr = True
    elif ex["type"] == "weight" and body.weight > (prev_best["weight"] or 0):
        is_pr = True
    elif ex["type"] == "reps" and body.reps > (prev_best["reps"] or 0):
        is_pr = True
    return {"status": "saved", "exercise": ex["name"], "is_pr": is_pr, "date": d}


@app.get("/api/training/exercise-logs")
def exercise_logs(user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM workout_log WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/training/records")
def records(user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM workout_log WHERE user_id = ?", (user_id,)).fetchall()
    by_ex = {}
    for r in rows:
        by_ex.setdefault(r["exercise_id"], []).append(r)
    result = []
    for ex_id, ex_rows in by_ex.items():
        ex_type = ex_rows[0]["type"]
        best = best_of(ex_type, ex_rows)
        result.append({
            "exercise_id": ex_id, "exercise_name": ex_rows[0]["exercise_name"], "type": ex_type,
            "best_weight": best["weight"], "best_reps": best["reps"], "date": best["date"],
        })
    result.sort(key=lambda x: x["exercise_name"])
    return result


@app.get("/api/training/progression/{exercise_id}")
def progression(exercise_id: str, user_id: int = Depends(get_current_user)):
    ex = get_exercise(exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM workout_log WHERE exercise_id = ? AND user_id = ? ORDER BY id DESC",
            (exercise_id, user_id),
        ).fetchall()
    if not rows:
        return {"exercise": ex["name"], "type": ex["type"], "has_history": False,
                "suggestion": "Залогируй первый подход — и тренер подскажет, как прогрессировать."}
    last = dict(rows[0])
    return {
        "exercise": ex["name"], "type": ex["type"], "has_history": True,
        "last": {"sets": last["sets"], "reps": last["reps"], "weight": last["weight"], "date": last["date"]},
        "record": best_of(ex["type"], rows),
        "suggestion": suggest_progression(ex["type"], last),
    }


# ===============================
# RECOVERY SCORE
# ===============================
@app.get("/api/recovery")
def recovery(user_id: int = Depends(get_current_user)):
    latest = get_latest_log(user_id)
    if not latest:
        return {"has_data": False, "recovery_score": None, "status": "Нет записей. Заполни чек-ин."}
    sleep = latest.get("sleep_hours") or 0
    fatigue = latest.get("fatigue")
    if fatigue is None:
        fatigue = 5
    sleep_score = min(sleep / 8, 1) * 50
    fatigue_score = (10 - fatigue) / 10 * 50
    score = max(0, min(100, round(sleep_score + fatigue_score)))
    if score >= 75:
        status = "Отличное восстановление — можно работать тяжело"
    elif score >= 50:
        status = "Среднее — тренируйся, но следи за нагрузкой"
    else:
        status = "Низкое — лёгкая тренировка или отдых"
    return {"has_data": True, "recovery_score": score, "status": status, "sleep_hours": sleep, "fatigue": fatigue}


# ===============================
# AI ЧАТ
# ===============================
@app.post("/api/chat")
def chat(body: ChatIn, user_id: int = Depends(get_current_user)):
    profile = get_profile(user_id)
    latest = get_latest_log(user_id)
    weekly = get_weekly_stats(user_id)
    plan = build_nutrition_plan(profile)
    with get_db() as conn:
        history_rows = conn.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id ASC", (user_id,)
        ).fetchall()
        history = [dict(r) for r in history_rows]
        reply = get_ai_response(body.message, history, profile=profile, latest_log=latest,
                                weekly_stats=weekly, nutrition_plan=plan)
        conn.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
                     (user_id, "user", body.message))
        conn.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
                     (user_id, "assistant", reply))
    return {"reply": reply}


@app.get("/api/chat/history")
def chat_history(user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content, created_at FROM chat_history WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/chat/history")
def clear_chat(user_id: int = Depends(get_current_user)):
    with get_db() as conn:
        conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    return {"status": "cleared"}


# ===============================
# РАЗДАЧА ФРОНТЕНДА (В КОНЦЕ)
# ===============================
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(os.path.join(FRONTEND_DIR, "favicon.svg"), media_type="image/svg+xml")


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")