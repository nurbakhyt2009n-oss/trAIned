# ===============================
# trAIned — FastAPI СЕРВЕР (API)
# v2.0 — мультипользовательский режим
# ===============================

import os
import sqlite3
import hashlib
import secrets
from contextlib import contextmanager
from datetime import date as _date
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from backend.database import get_connection, init_db
    from backend.calculations import get_full_nutrition_plan
    from backend.ai_coach import get_ai_response, generate_workout_plan, generate_meal_plan, analyze_food_photo, analyze_food_text
    from backend.exercises import get_exercise, get_grouped, suggest_progression
except ImportError:
    from database import get_connection, init_db
    from calculations import get_full_nutrition_plan
    from ai_coach import get_ai_response, generate_workout_plan, generate_meal_plan, analyze_food_photo, analyze_food_text
    from exercises import get_exercise, get_grouped, suggest_progression


app = FastAPI(title="trAIned API", version="2.0")

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


@app.exception_handler(sqlite3.Error)
async def db_error_handler(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Ошибка базы данных. Попробуй ещё раз."})


# ===============================
# АВТОРИЗАЦИЯ
# Пароли: PBKDF2 (100k итераций, соль). Сессии: токен в таблице sessions.
# ===============================
def hash_password(password: str, salt: str = None) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_password(password, salt), stored)


def get_current_user(authorization: str = Header(default="")) -> int:
    """Достаёт user_id из заголовка Authorization: Bearer <token>."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется вход")
    token = authorization[7:].strip()
    with get_db() as conn:
        row = conn.execute("SELECT user_id FROM sessions WHERE token = ?", (token,)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Сессия истекла — войди заново")
    return row["user_id"]


# ===============================
# МОДЕЛИ ДАННЫХ
# ===============================
class AuthIn(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=4, max_length=100)


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    age: int = Field(ge=12, le=100)
    gender: Literal["male", "female"]
    height: float = Field(ge=120, le=230)
    weight: float = Field(ge=30, le=250)
    goal: Literal["muscle_gain", "fat_loss", "recomposition", "maintenance", "endurance"]
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"]
    experience: Literal["Beginner", "Intermediate", "Advanced"] = "Intermediate"
    injuries: str = Field(default="нет", max_length=500)
    pullups_max: int = Field(default=0, ge=0, le=100)
    bench_max: float = Field(default=0, ge=0, le=400)


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
# АВТОРИЗАЦИЯ: РЕГИСТРАЦИЯ / ВХОД / ВЫХОД
# ===============================
@app.post("/api/auth/register")
def register(body: AuthIn):
    username = body.username.strip().lower()
    with get_db() as conn:
        exists = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="Такой логин уже занят")
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(body.password)),
        )
        user_id = cur.lastrowid
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    return {"token": token, "username": username}


@app.post("/api/auth/login")
def login(body: AuthIn):
    username = body.username.strip().lower()
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user or not verify_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Неверный логин или пароль")
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user["id"]))
    return {"token": token, "username": username}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default="")):
    token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if token:
        with get_db() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    return {"status": "logged_out"}


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
        conn.execute("DELETE FROM profile WHERE user_id = ?", (user_id,))
        conn.execute(
            """INSERT INTO profile
               (user_id, name, age, gender, height, weight, goal, experience,
                activity_level, injuries, pullups_max, bench_max)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, p.name, p.age, p.gender, p.height, p.weight, p.goal, p.experience,
             p.activity_level, p.injuries, p.pullups_max, p.bench_max),
        )
    profile = get_profile(user_id)
    return {"profile": profile, "nutrition_plan": build_nutrition_plan(profile)}


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
    return {"workout": generate_workout_plan(profile, get_latest_log(user_id))}


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
        raise HTTPException(status_code=404, detail="Нет записей. Заполни дневник.")
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
    return {"recovery_score": score, "status": status, "sleep_hours": sleep, "fatigue": fatigue}


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
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")