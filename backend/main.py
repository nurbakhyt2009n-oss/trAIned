# ===============================
# trAIned — FastAPI СЕРВЕР (API)
# ===============================

import os
import sqlite3
from contextlib import contextmanager
from datetime import date as _date
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# --- Импорт твоих готовых модулей ---
try:
    from backend.database import get_connection, init_db
    from backend.calculations import get_full_nutrition_plan
    from backend.ai_coach import get_ai_response, generate_workout_plan, generate_meal_plan, analyze_food_photo, analyze_food_text, estimate_food_text
    from backend.exercises import get_exercise, get_grouped, suggest_progression
except ImportError:
    from database import get_connection, init_db
    from calculations import get_full_nutrition_plan
    from ai_coach import get_ai_response, generate_workout_plan, generate_meal_plan, analyze_food_photo, analyze_food_text, estimate_food_text
    from exercises import get_exercise, get_grouped, suggest_progression


# ===============================
# ПРИЛОЖЕНИЕ
# ===============================
app = FastAPI(title="trAIned API", version="1.4")

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
# МОДЕЛИ ДАННЫХ
# ===============================
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
    image: str = Field(min_length=10, max_length=8_000_000)  # data:image/...;base64,...


class FoodTextIn(BaseModel):
    description: str = Field(min_length=2, max_length=500)


class FoodTextIn(BaseModel):
    description: str = Field(min_length=2, max_length=500)


class ExerciseLogIn(BaseModel):
    exercise_id: str = Field(min_length=1, max_length=50)
    sets: int = Field(ge=1, le=20)
    reps: int = Field(ge=1, le=300)  # до 300 — планка и статика логируются в секундах
    weight: float = Field(default=0, ge=0, le=500)
    date: Optional[str] = None
    notes: str = Field(default="", max_length=300)


# ===============================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ===============================
def get_profile():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM profile ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def get_latest_log():
    with get_db() as conn:
        row = conn.execute("SELECT * FROM training_log ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def get_weekly_stats():
    with get_db() as conn:
        rows = conn.execute("SELECT sleep_hours, fatigue FROM training_log ORDER BY id DESC LIMIT 7").fetchall()
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
    """Лучший результат из списка записей: по весу или по повторам."""
    if not rows:
        return None
    if ex_type == "weight":
        top = max(rows, key=lambda r: (r["weight"] or 0, r["reps"] or 0))
        return {"weight": top["weight"], "reps": top["reps"], "date": top["date"]}
    else:
        top = max(rows, key=lambda r: (r["reps"] or 0))
        return {"weight": top["weight"], "reps": top["reps"], "date": top["date"]}


# ===============================
# ПРОВЕРКА ЖИЗНИ
# ===============================
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "trAIned"}


# ===============================
# ПРОФИЛЬ
# ===============================
@app.post("/api/profile")
def save_profile(p: ProfileIn):
    with get_db() as conn:
        conn.execute("DELETE FROM profile")
        conn.execute(
            """INSERT INTO profile
               (name, age, gender, height, weight, goal, experience,
                activity_level, injuries, pullups_max, bench_max)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p.name, p.age, p.gender, p.height, p.weight, p.goal, p.experience,
             p.activity_level, p.injuries, p.pullups_max, p.bench_max),
        )
    profile = get_profile()
    return {"profile": profile, "nutrition_plan": build_nutrition_plan(profile)}


@app.get("/api/profile")
def read_profile():
    profile = get_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    return profile


# ===============================
# ПИТАНИЕ
# ===============================
@app.get("/api/nutrition/plan")
def nutrition_plan():
    profile = get_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="Сначала заполни профиль")
    return build_nutrition_plan(profile)


@app.post("/api/nutrition/meal-plan")
def meal_plan(body: MealPlanIn):
    profile = get_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="Сначала заполни профиль")
    return {"meal_plan": generate_meal_plan(build_nutrition_plan(profile), body.preferences)}


@app.post("/api/nutrition/log")
def log_nutrition(body: NutritionLogIn):
    d = body.date or _date.today().isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO nutrition_log (date, calories, protein, fat, carbs, water, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (d, body.calories, body.protein, body.fat, body.carbs, body.water, body.notes),
        )
    return {"status": "saved", "date": d}


@app.get("/api/nutrition/logs")
def nutrition_logs():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM nutrition_log ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


# ===============================
# ТРЕНИРОВКИ — дневник состояния
# ===============================
@app.post("/api/training/workout")
def workout():
    profile = get_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="Сначала заполни профиль")
    return {"workout": generate_workout_plan(profile, get_latest_log())}


@app.post("/api/training/log")
def log_training(body: DailyLogIn):
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM training_log").fetchone()["c"]
        day = count + 1
        conn.execute(
            """INSERT INTO training_log (day, sleep_hours, fatigue, weight, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (day, body.sleep_hours, body.fatigue, body.weight, body.notes),
        )
    return {"status": "saved", "day": day}


@app.get("/api/training/logs")
def training_logs():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM training_log ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


# ===============================
# ТРЕНИРОВКИ — журнал упражнений (НОВОЕ)
# ===============================
@app.get("/api/exercises")
def exercises():
    """Библиотека упражнений, сгруппированная по категориям."""
    return get_grouped()


@app.post("/api/training/exercise-log")
def log_exercise(body: ExerciseLogIn):
    """Записать выполненное упражнение (подходы × повторы × вес)."""
    ex = get_exercise(body.exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")

    d = body.date or _date.today().isoformat()

    with get_db() as conn:
        # прошлый лучший результат — чтобы понять, новый ли это рекорд
        prior = conn.execute(
            "SELECT reps, weight, date FROM workout_log WHERE exercise_id = ?",
            (body.exercise_id,),
        ).fetchall()

        conn.execute(
            """INSERT INTO workout_log (date, exercise_id, exercise_name, type, sets, reps, weight, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (d, ex["id"], ex["name"], ex["type"], body.sets, body.reps, body.weight, body.notes),
        )

    # проверка личного рекорда
    prev_best = best_of(ex["type"], prior)
    is_pr = False
    if prev_best is None:
        is_pr = True  # первая запись — всегда рекорд
    elif ex["type"] == "weight" and body.weight > (prev_best["weight"] or 0):
        is_pr = True
    elif ex["type"] == "reps" and body.reps > (prev_best["reps"] or 0):
        is_pr = True

    return {"status": "saved", "exercise": ex["name"], "is_pr": is_pr, "date": d}


@app.get("/api/training/exercise-logs")
def exercise_logs():
    """Вся история залогированных упражнений (для журнала)."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM workout_log ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/training/records")
def records():
    """Личные рекорды по каждому упражнению, где есть история."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM workout_log").fetchall()

    by_ex = {}
    for r in rows:
        by_ex.setdefault(r["exercise_id"], []).append(r)

    result = []
    for ex_id, ex_rows in by_ex.items():
        ex_type = ex_rows[0]["type"]
        best = best_of(ex_type, ex_rows)
        result.append({
            "exercise_id": ex_id,
            "exercise_name": ex_rows[0]["exercise_name"],
            "type": ex_type,
            "best_weight": best["weight"],
            "best_reps": best["reps"],
            "date": best["date"],
        })
    result.sort(key=lambda x: x["exercise_name"])
    return result


@app.get("/api/training/progression/{exercise_id}")
def progression(exercise_id: str):
    """Последний результат + подсказка по прогрессивной перегрузке для упражнения."""
    ex = get_exercise(exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM workout_log WHERE exercise_id = ? ORDER BY id DESC",
            (exercise_id,),
        ).fetchall()

    if not rows:
        return {
            "exercise": ex["name"], "type": ex["type"], "has_history": False,
            "suggestion": "Залогируй первый подход — и тренер подскажет, как прогрессировать.",
        }

    last = dict(rows[0])
    return {
        "exercise": ex["name"],
        "type": ex["type"],
        "has_history": True,
        "last": {"sets": last["sets"], "reps": last["reps"], "weight": last["weight"], "date": last["date"]},
        "record": best_of(ex["type"], rows),
        "suggestion": suggest_progression(ex["type"], last),
    }


@app.post("/api/nutrition/analyze-photo")
def analyze_photo(body: PhotoIn):
    """Распознать еду на фото и оценить КБЖУ (vision-модель)."""
    result = analyze_food_photo(body.image)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail="Не удалось распознать фото. Попробуй другое фото.")
    return result["data"]


@app.post("/api/nutrition/analyze-text")
def analyze_text(body: FoodTextIn):
    """Оценить КБЖУ по текстовому описанию (название + порция)."""
    result = estimate_food_text(body.description)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail="Не удалось оценить. Попробуй описать иначе.")
    return result["data"]


@app.post("/api/nutrition/analyze-text")
def analyze_text(body: FoodTextIn):
    """Оценить КБЖУ по текстовому описанию еды."""
    result = analyze_food_text(body.description)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail="Не удалось оценить. Попробуй описать иначе.")
    return result["data"]


@app.get("/api/nutrition/today")
def nutrition_today():
    """Сводка за сегодня: цель, сколько съедено, что осталось, список приёмов пищи."""
    profile = get_profile()
    target = build_nutrition_plan(profile) if profile else None
    today = _date.today().isoformat()

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM nutrition_log WHERE date = ? ORDER BY id ASC", (today,)
        ).fetchall()
    entries = [dict(r) for r in rows]

    consumed = {
        "calories": round(sum(e["calories"] or 0 for e in entries)),
        "protein": round(sum(e["protein"] or 0 for e in entries)),
        "fat": round(sum(e["fat"] or 0 for e in entries)),
        "carbs": round(sum(e["carbs"] or 0 for e in entries)),
    }
    return {"date": today, "target": target, "consumed": consumed, "entries": entries}


@app.delete("/api/nutrition/log/{entry_id}")
def delete_nutrition_log(entry_id: int):
    """Удалить приём пищи из дневника."""
    with get_db() as conn:
        conn.execute("DELETE FROM nutrition_log WHERE id = ?", (entry_id,))
    return {"status": "deleted"}


# ===============================
# RECOVERY SCORE
# ===============================
@app.get("/api/recovery")
def recovery():
    latest = get_latest_log()
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
def chat(body: ChatIn):
    profile = get_profile()
    latest = get_latest_log()
    weekly = get_weekly_stats()
    plan = build_nutrition_plan(profile)

    with get_db() as conn:
        history_rows = conn.execute("SELECT role, content FROM chat_history ORDER BY id ASC").fetchall()
        history = [dict(r) for r in history_rows]

        reply = get_ai_response(
            body.message, history, profile=profile, latest_log=latest,
            weekly_stats=weekly, nutrition_plan=plan,
        )

        conn.execute("INSERT INTO chat_history (role, content) VALUES (?, ?)", ("user", body.message))
        conn.execute("INSERT INTO chat_history (role, content) VALUES (?, ?)", ("assistant", reply))

    return {"reply": reply}


@app.get("/api/chat/history")
def chat_history():
    with get_db() as conn:
        rows = conn.execute("SELECT role, content, created_at FROM chat_history ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


@app.delete("/api/chat/history")
def clear_chat():
    with get_db() as conn:
        conn.execute("DELETE FROM chat_history")
    return {"status": "cleared"}


# ===============================
# РАЗДАЧА ФРОНТЕНДА (В КОНЦЕ)
# ===============================
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")