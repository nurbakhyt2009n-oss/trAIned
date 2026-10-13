# ===============================
# AI ТРЕНЕР — МОЗГ ПРИЛОЖЕНИЯ
# ===============================
import os
import re
import json
from groq import Groq
from dotenv import load_dotenv

# Читаем переменные окружения из файла .env (он лежит в корне проекта)
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise RuntimeError(
        "Не найден GROQ_API_KEY. Создай файл .env в корне проекта "
        "и впиши строку:  GROQ_API_KEY=твой_ключ"
    )

# timeout=30 — если Groq не ответит за 30 секунд, получим ошибку, а не вечное ожидание
client = Groq(api_key=GROQ_API_KEY, timeout=30.0)

# Модели Groq. Groq периодически выключает старые модели (llama-3.3 и llama-4-scout
# отключены летом 2026), поэтому имена можно поменять в .env / на Render без правки кода:
#   GROQ_TEXT_MODEL=...   GROQ_VISION_MODEL=...
# Список актуальных моделей: https://console.groq.com/docs/models
def _models(env_name, defaults):
    custom = [m.strip() for m in os.getenv(env_name, "").split(",") if m.strip()]
    return custom + [m for m in defaults if m not in custom]


TEXT_MODELS = _models("GROQ_TEXT_MODEL", ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"])
VISION_MODELS = _models("GROQ_VISION_MODEL", ["qwen/qwen3.8-27b"])


def _reasoning_params(model):
    """Новые модели Groq «думают» перед ответом — отключаем/урезаем это, чтобы ответ был быстрым."""
    if "gpt-oss" in model:
        return {"reasoning_effort": "low", "include_reasoning": False}
    if "qwen" in model:
        return {"reasoning_effort": "none"}
    return {}


def _complete(models, messages, max_tokens, temperature, json_mode=False):
    """Запрос к Groq с запасными моделями. Возвращает текст ответа или бросает исключение."""
    last_error = None
    for model in models:
        extra = _reasoning_params(model)
        # у reasoning-моделей лимит включает «мысли» — даём запас
        limit = max_tokens + (1500 if "gpt-oss" in model else 0)
        kwargs = dict(model=model, messages=messages, temperature=temperature, max_tokens=limit)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        for attempt_extra in (extra, {}):        # если параметр не поддерживается — пробуем без него
            try:
                resp = client.chat.completions.create(**kwargs, extra_body=attempt_extra or None)
                text = _strip_thinking(resp.choices[0].message.content or "")
                if text:
                    return text
                last_error = RuntimeError(f"{model}: empty response")
                break
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                if attempt_extra and ("reasoning" in msg or "unsupported" in msg or "invalid" in msg):
                    continue                     # повторить без reasoning-параметров
                break                            # модель недоступна — следующая модель
        print(f"[ai] model {model} failed: {last_error}")
    raise last_error or RuntimeError("no models configured")


def _strip_thinking(text):
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _parse_food_json(text):
    """JSON с оценкой еды: терпим ```json-обёртки и лишний текст, приводим числа."""
    try:
        data = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise
        data = json.loads(m.group(0))
    for key in ("calories", "protein", "fat", "carbs"):
        val = data.get(key, 0)
        if isinstance(val, str):
            num = re.search(r"\d+(?:[.,]\d+)?", val)
            val = float(num.group(0).replace(",", ".")) if num else 0
        data[key] = round(float(val or 0))
    data.setdefault("dish", "Блюдо")
    data.setdefault("confidence", "medium")
    data.setdefault("note", "")
    return data


def build_system_prompt(profile, latest_log, weekly_stats, nutrition_plan):
    """Формируем системный промпт с полным контекстом атлета"""

    prompt = """Ты — персональный AI тренер и нутрициолог. 
Твоя задача — давать конкретные, персонализированные советы основанные на реальных данных атлета.
Отвечай на русском языке. Будь прямым, конкретным, как опытный тренер — без воды.
Не ставь медицинские диагнозы. При травмах и болях отправляй к врачу.
Пиши простым текстом, без эмодзи.\n\n"""

    if profile:
        prompt += f"""ПРОФИЛЬ АТЛЕТА:
- Имя: {profile.get('name', 'Атлет')}
- Возраст: {profile.get('age', '—')} лет
- Пол: {'Мужской' if profile.get('gender') == 'male' else 'Женский'}
- Рост: {profile.get('height', '—')} см
- Вес: {profile.get('weight', '—')} кг
- Цель: {profile.get('goal', '—')}
- Уровень: {profile.get('experience', '—')}
- Активность: {profile.get('activity_level', '—')}
- Травмы/ограничения: {profile.get('injuries', 'нет')}
- Макс. подтягиваний: {profile.get('pullups_max', 0)} раз
- Жим лёжа 1ПМ: {profile.get('bench_max', 0)} кг\n\n"""

    if latest_log:
        prompt += f"""СОСТОЯНИЕ СЕГОДНЯ:
- Сон: {latest_log.get('sleep_hours', '—')} часов
- Усталость: {latest_log.get('fatigue', '—')}/10
- Вес: {latest_log.get('weight', '—')} кг
- Заметки: {latest_log.get('notes', 'нет')}\n\n"""

    if weekly_stats:
        prompt += f"""СТАТИСТИКА ЗА НЕДЕЛЮ:
- Средний сон: {weekly_stats.get('avg_sleep', '—')} ч
- Средняя усталость: {weekly_stats.get('avg_fatigue', '—')}/10
- Записей: {weekly_stats.get('days_logged', 0)} дней\n\n"""

    if nutrition_plan:
        prompt += f"""ПЛАН ПИТАНИЯ:
- Цель: {nutrition_plan.get('target_calories', '—')} ккал
- Белки: {nutrition_plan.get('protein', '—')} г
- Жиры: {nutrition_plan.get('fat', '—')} г
- Углеводы: {nutrition_plan.get('carbs', '—')} г
- Вода: {nutrition_plan.get('water', '—')} л\n\n"""

    return prompt


def get_ai_response(user_message, chat_history, profile=None, latest_log=None,
                    weekly_stats=None, nutrition_plan=None):
    """Получить ответ от AI тренера"""
    system_prompt = build_system_prompt(profile, latest_log, weekly_stats, nutrition_plan)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        return _complete(TEXT_MODELS, messages, max_tokens=700, temperature=0.7)
    except Exception as e:
        print(f"[ai] chat error: {e}")
        return "Тренер сейчас недоступен. Попробуй ещё раз через минуту."


def _format_planned(planned):
    lines = []
    for e in planned.get("exercises", []):
        line = f"- {e['name']}: {e['sets']} x {e['reps']} {e.get('unit', '')}".rstrip()
        if e.get("hint"):
            line += f" ({e['hint']})"
        lines.append(line)
    return "\n".join(lines)


def generate_workout_plan(profile, latest_log, planned=None):
    """Тренировка на сегодня. Если есть программа — адаптирует запланированный день."""
    fatigue = latest_log.get('fatigue', 5) if latest_log else 5
    sleep = latest_log.get('sleep_hours', 7) if latest_log else 7
    goal = profile.get('goal', 'muscle_gain') if profile else 'muscle_gain'
    pullups = profile.get('pullups_max', 10) if profile else 10
    bench = profile.get('bench_max', 60) if profile else 60
    injuries = profile.get('injuries', 'нет') if profile else 'нет'

    prompt = f"""Составь конкретную тренировку на сегодня для атлета.

Данные:
- Усталость: {fatigue}/10
- Сон: {sleep} часов
- Цель: {goal}
- Уровень: {profile.get('experience', '—') if profile else '—'}
- Макс подтягивания: {pullups} раз
- Жим лёжа 1ПМ: {bench} кг
- Травмы: {injuries}

Формат ответа:
1. Тип тренировки (Push/Pull/Legs/Full Body/Отдых)
2. Разминка (2-3 упражнения)
3. Основная часть (4-6 упражнений с подходами и повторениями)
4. Заминка
5. Одна ключевая рекомендация на сегодня
Пиши простым текстом, без эмодзи.

Если усталость выше 7 или сон меньше 6 часов — предложи лёгкую восстановительную тренировку или отдых."""

    if planned and planned.get("exercises"):
        prompt += f"""

По программе атлета сегодня: {planned.get('name')} ({planned.get('focus')}).
{_format_planned(planned)}

Не придумывай новую тренировку: возьми этот план и адаптируй под сон и усталость
(можно уменьшить подходы, вес или заменить упражнение). Объясни, что изменил и почему."""

    try:
        return _complete(TEXT_MODELS, [{"role": "user", "content": prompt}],
                         max_tokens=900, temperature=0.6)
    except Exception as e:
        print(f"[ai] workout error: {e}")
        return "Не удалось составить тренировку. Попробуй ещё раз через минуту."


def generate_meal_plan(nutrition_plan, preferences="обычное питание"):
    """Генерация меню на день"""
    if not nutrition_plan:
        return "Сначала заполни профиль чтобы рассчитать план питания."

    prompt = f"""Составь меню на день для атлета.

Цели по питанию:
- Калории: {nutrition_plan.get('target_calories')} ккал
- Белки: {nutrition_plan.get('protein')} г
- Жиры: {nutrition_plan.get('fat')} г
- Углеводы: {nutrition_plan.get('carbs')} г
- Предпочтения: {preferences}

Формат:
- Завтрак (с граммовками)
- Перекус
- Обед (с граммовками)
- Перекус после тренировки
- Ужин (с граммовками)
- Итого КБЖУ

Используй простые, доступные продукты. Без эмодзи."""

    try:
        return _complete(TEXT_MODELS, [{"role": "user", "content": prompt}],
                         max_tokens=900, temperature=0.6)
    except Exception as e:
        print(f"[ai] meal plan error: {e}")
        return "Не удалось составить меню. Попробуй ещё раз через минуту."


def analyze_food_photo(image_data_url):
    """
    Распознать еду на фото и оценить КБЖУ через vision-модель.
    image_data_url — строка вида 'data:image/jpeg;base64,...'
    Возвращает {"ok": True, "data": {...}} или {"ok": False, "error": "..."}.
    """
    prompt = """Ты — нутрициолог. На фото — еда (могут быть блюда Центральной Азии и Казахстана:
бешбармак, плов, манты, лагман, самса, шашлык, баурсаки и другие).
Определи блюдо и оцени пищевую ценность ПОРЦИИ, которая видна на фото.
Если на тарелке несколько блюд — оцени суммарно. Будь реалистичен по размеру порции.
Это оценка по фотографии, не точный анализ.

Верни СТРОГО валидный JSON без пояснений и markdown:
{
  "dish": "название блюда на русском",
  "calories": число_ккал,
  "protein": число_грамм,
  "fat": число_грамм,
  "carbs": число_грамм,
  "confidence": "high" или "medium" или "low",
  "note": "короткий комментарий одним предложением"
}"""

    try:
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }]
        text = _complete(VISION_MODELS, messages, max_tokens=500, temperature=0.3, json_mode=True)
        return {"ok": True, "data": _parse_food_json(text)}
    except Exception as e:
        print(f"[ai] photo error: {e}")
        return {"ok": False, "error": str(e)}


def analyze_food_text(description):
    """
    Оценить КБЖУ по текстовому описанию еды («бешбармак, большая тарелка ~400 г»).
    Возвращает {"ok": True, "data": {...}} или {"ok": False, "error": "..."}.
    """
    prompt = f"""Ты — нутрициолог. Пользователь описал приём пищи словами
(возможны блюда Центральной Азии и Казахстана: бешбармак, плов, манты, лагман, самса, баурсаки и т.д.).
Оцени пищевую ценность порции по описанию: "{description}"
Если размер порции не указан — считай стандартную порцию и отметь это в note.

Верни СТРОГО валидный JSON без пояснений и markdown:
{{
  "dish": "название блюда на русском",
  "calories": число_ккал,
  "protein": число_грамм,
  "fat": число_грамм,
  "carbs": число_грамм,
  "confidence": "high" или "medium" или "low",
  "note": "короткий комментарий одним предложением"
}}"""

    try:
        text = _complete(TEXT_MODELS, [{"role": "user", "content": prompt}],
                         max_tokens=400, temperature=0.3, json_mode=True)
        return {"ok": True, "data": _parse_food_json(text)}
    except Exception as e:
        print(f"[ai] food text error: {e}")
        return {"ok": False, "error": str(e)}


# ===============================
# ТЕСТ
# ===============================
if __name__ == "__main__":
    test_profile = {"name": "Атлет", "age": 18, "gender": "male", "height": 170,
                    "weight": 54, "goal": "muscle_gain", "experience": "Intermediate",
                    "activity_level": "active", "injuries": "нет",
                    "pullups_max": 20, "bench_max": 75}
    test_log = {"sleep_hours": 7.5, "fatigue": 4, "weight": 54}

    print("Тест AI тренера...")
    print(get_ai_response("Могу я сегодня тренироваться интенсивно?", [],
                          profile=test_profile, latest_log=test_log))