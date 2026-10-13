# ===============================
# ГЕНЕРАТОР ПРОГРАММЫ ТРЕНИРОВОК
# Строит 4-недельный план под профиль: уровень (Beginner -> Pro), цель,
# дни в неделю, инвентарь, травмы и силовые показатели.
# Без AI: одинаковый профиль всегда даёт одинаковый план.
# ===============================
from datetime import date

try:
    from backend.exercises import EXERCISES
except ImportError:
    from exercises import EXERCISES


LEVELS = ["Beginner", "Intermediate", "Advanced", "Pro"]
LEVEL_LABELS = {"Beginner": "Новичок", "Intermediate": "Средний",
                "Advanced": "Продвинутый", "Pro": "Профи / спортсмен"}
EX_LEVEL_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2}
EQUIPMENT_IDS = ["bodyweight", "dumbbells", "gym", "band"]
EQUIP_PRIORITY = {"gym": 3, "dumbbells": 2, "band": 1, "bodyweight": 0}
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# двигательный паттерн каждого упражнения из библиотеки
PATTERN = {
    "pushups_knee": "h_push", "pushups": "h_push", "db_bench": "h_push",
    "bench_press": "h_push", "band_chest_press": "h_push",
    "incline_bench": "incline_push", "db_fly": "chest_iso",
    "pike_pushups": "v_push", "hspu": "v_push", "db_shoulder_press": "v_push", "overhead_press": "v_push",
    "dips": "dip", "dips_bench": "triceps", "triceps_pushdown": "triceps",
    "lateral_raise": "delts",
    "aussie_pullups": "h_pull", "db_row": "h_pull", "barbell_row": "h_pull", "band_row": "h_pull",
    "neg_pullups": "v_pull", "pullups": "v_pull", "chinups": "v_pull", "wide_pullups": "v_pull",
    "lat_pulldown": "v_pull", "muscle_up": "skill_pull",
    "db_curl": "biceps", "hammer_curl": "biceps", "barbell_curl": "biceps", "band_curl": "biceps",
    "face_pull": "rear_delt", "band_pull_apart": "rear_delt",
    "bw_squat": "squat", "goblet_squat": "squat", "squat": "squat", "front_squat": "squat",
    "leg_press": "squat", "band_squat": "squat", "pistol_squat": "squat",
    "lunges_bw": "lunge", "db_lunges": "lunge",
    "db_romanian": "hinge", "deadlift": "hinge",
    "glute_bridge": "glute", "hip_thrust": "glute",
    "leg_curl": "hamstring", "leg_extension": "quad_iso",
    "calf_raise_bw": "calf",
    "plank": "core", "side_plank": "core", "dead_bug": "core", "ab_wheel": "core",
    "crunches": "core_flex", "hanging_knee_raise": "core_flex", "hanging_leg_raise": "core_flex",
    "russian_twist": "core_flex",
}

PULLUP_FAMILY = {"pullups", "chinups", "wide_pullups", "muscle_up"}
HOLDS = {"plank", "side_plank"}
# облегчённые варианты — только для тех, кому база пока тяжела
EASIER_VARIANTS = {"pushups_knee"}
# упражнения-навыки: фиксированный диапазон повторов
SKILL_REPS = {"neg_pullups": (3, 6), "hspu": (3, 8), "pistol_squat": (4, 8),
              "muscle_up": (2, 5), "ab_wheel": (6, 12)}
# коэффициенты от жима лёжа 1ПМ (для подсказки веса)
BENCH_FACTORS = {"bench_press": (1.0, ""), "incline_bench": (0.8, ""),
                 "db_bench": (0.38, " на каждую руку")}

# травмы: ключевые слова -> что убрать из программы
INJURY_RULES = [
    (("плеч", "shoulder", "ротатор"), "плечо",
     {"overhead_press", "db_shoulder_press", "hspu", "pike_pushups", "dips", "muscle_up", "wide_pullups"},
     "убраны жимы над головой и брусья"),
    (("колен", "knee", "менис"), "колени",
     {"pistol_squat", "lunges_bw", "db_lunges", "front_squat", "leg_extension"},
     "убраны выпады, пистолетики и разгибания ног"),
    (("спин", "поясниц", "back", "грыж", "протруз"), "спина",
     {"deadlift", "barbell_row", "squat", "front_squat", "russian_twist", "hanging_leg_raise"},
     "убраны становая, тяга в наклоне и приседания со штангой"),
    (("запяст", "wrist"), "запястья",
     {"hspu", "pike_pushups", "muscle_up", "front_squat"},
     "убраны стойки на руках и фронтальные приседания"),
    (("локт", "elbow"), "локти",
     {"dips", "dips_bench", "muscle_up", "barbell_curl"},
     "убраны брусья и подъём штанги на бицепс"),
]

# ---------- шаблоны тренировочных дней: (роль, [паттерны по приоритету]) ----------
DAY_TEMPLATES = {
    "full_a": ("Всё тело A", "Присед + горизонтальный жим и тяга", [
        ("main", ["squat"]), ("main", ["h_push"]), ("secondary", ["h_pull"]),
        ("secondary", ["hinge", "glute"]), ("accessory", ["delts", "rear_delt"]), ("core", ["core"])]),
    "full_b": ("Всё тело B", "Тяга бёдрами + вертикальные жим и тяга", [
        ("main", ["hinge", "glute"]), ("main", ["v_pull"]), ("secondary", ["v_push", "incline_push"]),
        ("secondary", ["lunge", "squat"]), ("accessory", ["biceps"]), ("core", ["core_flex", "core"])]),
    "full_c": ("Всё тело C", "Объём и слабые места", [
        ("main", ["squat"]), ("secondary", ["h_push", "incline_push"]), ("secondary", ["v_pull", "h_pull"]),
        ("accessory", ["glute", "hamstring"]), ("accessory", ["triceps"]), ("core", ["core"])]),
    "upper_a": ("Верх A", "Горизонтальные жим и тяга", [
        ("main", ["h_push"]), ("main", ["h_pull"]), ("secondary", ["v_push"]),
        ("secondary", ["v_pull"]), ("accessory", ["delts"]), ("accessory", ["biceps"]),
        ("accessory", ["triceps"])]),
    "upper_b": ("Верх B", "Вертикальная тяга и жим под углом", [
        ("main", ["v_pull"]), ("main", ["incline_push", "h_push"]), ("secondary", ["h_pull"]),
        ("secondary", ["dip", "triceps"]), ("accessory", ["rear_delt", "delts"]),
        ("accessory", ["biceps"])]),
    "lower_a": ("Низ A", "Акцент на квадрицепс", [
        ("main", ["squat"]), ("secondary", ["hinge", "glute"]), ("secondary", ["lunge", "squat"]),
        ("accessory", ["hamstring", "glute"]), ("accessory", ["calf"]), ("core", ["core"])]),
    "lower_b": ("Низ B", "Акцент на заднюю цепь", [
        ("main", ["hinge", "glute"]), ("secondary", ["squat"]), ("secondary", ["glute", "hamstring"]),
        ("accessory", ["quad_iso", "lunge"]), ("accessory", ["calf"]), ("core", ["core_flex", "core"])]),
    "push": ("Push", "Грудь, плечи, трицепс", [
        ("main", ["h_push"]), ("main", ["v_push"]), ("secondary", ["incline_push", "h_push"]),
        ("secondary", ["dip", "chest_iso"]), ("accessory", ["delts"]), ("accessory", ["triceps"])]),
    "pull": ("Pull", "Спина, бицепс, задние дельты", [
        ("skill", ["skill_pull"]), ("main", ["v_pull"]), ("main", ["h_pull"]),
        ("secondary", ["v_pull", "h_pull"]), ("accessory", ["rear_delt"]), ("accessory", ["biceps"]),
        ("core", ["core_flex"])]),
    "legs": ("Legs", "Ноги и кор", [
        ("main", ["squat"]), ("main", ["hinge", "glute"]), ("secondary", ["lunge", "squat"]),
        ("secondary", ["glute", "hamstring"]), ("accessory", ["hamstring", "quad_iso"]),
        ("accessory", ["calf"]), ("core", ["core"])]),
}

# добивка, если из-за инвентаря/травм в дне осталось мало упражнений
FILLERS = [("accessory", ["rear_delt"]), ("core", ["core"]), ("core", ["core_flex"]), ("accessory", ["calf"])]
MIN_EXERCISES = 4

SPLITS = {
    "full_2":   ("Всё тело ×2", ["full_a", "full_b"]),
    "full_3":   ("Всё тело ×3", ["full_a", "full_b", "full_c"]),
    "ppl":      ("Push / Pull / Legs", ["push", "pull", "legs"]),
    "ul":       ("Верх / Низ", ["upper_a", "lower_a", "upper_b", "lower_b"]),
    "ul_ppl":   ("Верх / Низ + PPL", ["upper_a", "lower_a", "push", "pull", "legs"]),
    "ppl_2":    ("Push / Pull / Legs ×2", ["push", "pull", "legs", "push", "pull", "legs"]),
}
SCHEDULE = {2: [0, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 4, 5], 6: [0, 1, 2, 3, 4, 5]}

# повторы (мин, макс) и отдых (сек) по цели и роли упражнения
GOAL_SCHEME = {
    "muscle_gain":   {"main": (6, 10, 120), "secondary": (8, 12, 90), "accessory": (10, 15, 60)},
    "fat_loss":      {"main": (8, 12, 75),  "secondary": (10, 12, 60), "accessory": (12, 15, 45)},
    "recomposition": {"main": (6, 10, 120), "secondary": (8, 12, 90), "accessory": (10, 15, 60)},
    "maintenance":   {"main": (6, 10, 90),  "secondary": (8, 12, 75), "accessory": (10, 15, 60)},
    "endurance":     {"main": (12, 15, 60), "secondary": (15, 20, 45), "accessory": (15, 20, 30)},
}
BASE_SETS = [
    {"skill": 0, "main": 3, "secondary": 2, "accessory": 2, "core": 2},   # Beginner
    {"skill": 0, "main": 4, "secondary": 3, "accessory": 3, "core": 3},   # Intermediate
    {"skill": 3, "main": 4, "secondary": 3, "accessory": 3, "core": 3},   # Advanced
    {"skill": 4, "main": 5, "secondary": 4, "accessory": 3, "core": 3},   # Pro
]
HOLD_SECONDS = [(20, 30), (30, 45), (45, 60), (60, 90)]

# волнообразная интенсивность основных упражнений (Advanced / Pro)
INTENSITY = {
    "heavy":  {"label": "Тяжёлый день", "reps": (3, 5), "rest": 180},
    "medium": {"label": "Средний день", "reps": None, "rest": None},
    "light":  {"label": "Объёмный день", "reps": (10, 12), "rest": 90},
}

PROGRESSION = [
    {"model": "Линейная прогрессия",
     "rules": ["Сделал все подходы и повторы с запасом — в следующий раз добавь 2.5 кг (верх тела) или 5 кг (ноги).",
               "Упражнения с весом тела: добавляй 1–2 повтора за тренировку.",
               "Не получилось 2 тренировки подряд — сбрось вес на 10% и снова набирай."],
     "weeks": [(3, 0, "Техника", "Освой движения, вес лёгкий."),
               (2, 0, "Набор темпа", "Добавляй вес каждую тренировку, пока техника чистая."),
               (2, 0, "Прогресс", "Продолжай прибавлять. Записывай каждый подход в журнал."),
               (1, 0, "Проверка", "Последняя неделя цикла. Потом обнови максимумы в профиле — программа пересчитается.")]},
    {"model": "Двойная прогрессия",
     "rules": ["Работай в диапазоне повторов. Дошёл до верхней границы во всех подходах — добавь вес и начни снизу.",
               "Повторы в запасе (RIR) уменьшаются каждую неделю: 3 → 2 → 1.",
               "4-я неделя — разгрузка: меньше подходов, тот же вес."],
     "weeks": [(3, 0, "Вход", "Средняя нагрузка."),
               (2, 0, "Накопление", "Добавь повтор или вес, где можешь."),
               (1, 0, "Пик", "Самая тяжёлая неделя."),
               (4, "deload", "Разгрузка", "Подходов на ~40% меньше. Восстановись перед новым циклом.")]},
    {"model": "Блочная периодизация (3 + 1)",
     "rules": ["Основные упражнения чередуют тяжёлые и средние дни.",
               "3-я неделя — перегрузка: +1 подход в основных упражнениях.",
               "4-я неделя — разгрузка, затем новый цикл с весом чуть выше."],
     "weeks": [(3, 0, "Накопление", "Объём выше, интенсивность умеренная."),
               (2, 0, "Интенсификация", "Тяжелее, меньше повторов в запасе."),
               (1, 1, "Перегрузка", "+1 подход в основных упражнениях. Следи за сном."),
               (4, "deload", "Разгрузка", "Подходов на ~40% меньше, вес прежний.")]},
    {"model": "Волнообразная периодизация (DUP)",
     "rules": ["Основные упражнения идут по кругу: тяжёлый → средний → объёмный день.",
               "3-я неделя — перегрузка: +1 подход в основных и вспомогательных.",
               "В конце 4-й недели можно проверить максимумы и обновить профиль."],
     "weeks": [(2, 0, "Накопление", "Высокий объём."),
               (1, 0, "Интенсификация", "Тяжёлые дни — близко к максимуму, техника не страдает."),
               (1, 1, "Перегрузка", "+1 подход. Сон 8+ часов обязателен."),
               (4, "deload", "Разгрузка / тест", "Минимум объёма. По желанию — проверка 1ПМ и максимума подтягиваний.")]},
]

WARMUP = ["5 минут лёгкого кардио (скакалка, велосипед, быстрая ходьба)",
          "Суставная разминка: плечи, таз, колени, голеностоп",
          "2 разминочных подхода в первом упражнении: ~50% и ~75% рабочего веса"]
COOLDOWN = ["5 минут спокойной ходьбы", "Растяжка мышц, которые работали сегодня — по 30 секунд"]
FINISHER = {
    "fat_loss": "Финишер: 10–15 мин интервалов — 30 с быстро / 60 с спокойно",
    "endurance": "Кардио: 20–30 мин в зоне 2 (можешь говорить, но не петь)",
    "recomposition": "По желанию: 10 минут ходьбы в горку или велосипеда",
}
RECOVERY_DAY = ["Ходьба 30–45 минут", "Мобильность: 10 минут на плечи и таз", "Растяжка или йога 15 минут"]


# ===============================
# ВСПОМОГАТЕЛЬНОЕ
# ===============================
def _level_index(experience):
    return LEVELS.index(experience) if experience in LEVELS else 1


def parse_equipment(value):
    """'gym,dumbbells' или список -> список; своё тело есть у всех."""
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",")]
    else:
        items = list(value or [])
    items = [v for v in items if v in EQUIPMENT_IDS]
    if "bodyweight" not in items:
        items.append("bodyweight")
    return [e for e in EQUIPMENT_IDS if e in items]


def injury_exclusions(text):
    text = (text or "").lower()
    excluded, notes = set(), []
    if text.strip() in ("", "нет", "-", "no", "none"):
        return excluded, notes
    for keys, label, ids, note in INJURY_RULES:
        if any(k in text for k in keys):
            excluded |= ids
            notes.append(f"{label.capitalize()}: {note}.")
    return excluded, notes


def choose_split(days, level):
    if days <= 2:
        return "full_2"
    if days == 3:
        return "ppl" if level >= 2 else "full_3"
    if days == 4 or level == 0:
        return "ul"
    if days == 5:
        return "ul_ppl"
    return "ppl_2"


class _Ctx:
    def __init__(self, profile):
        self.level = _level_index(profile.get("experience"))
        self.max_rank = min(self.level, 2)
        self.goal = profile.get("goal") if profile.get("goal") in GOAL_SCHEME else "maintenance"
        self.equipment = parse_equipment(profile.get("equipment"))
        self.days = max(2, min(6, int(profile.get("days_per_week") or 3)))
        self.pullups_max = int(profile.get("pullups_max") or 0)
        self.bench_max = float(profile.get("bench_max") or 0)
        self.excluded, self.injury_notes = injury_exclusions(profile.get("injuries"))
        # 0 подтягиваний у новичка = не умеет; у опытного скорее "не знаю"
        if self.pullups_max == 0:
            self.pull_cap = -1 if self.level == 0 else self.max_rank
        elif self.pullups_max < 12:
            self.pull_cap = min(1, self.max_rank)
        else:
            self.pull_cap = self.max_rank
        # сила для выбора более лёгких/тяжёлых вариантов одного уровня
        self.strong = self.pullups_max >= 5 or self.bench_max >= 50 or self.level >= 1


def _allowed(ex, ctx):
    rank = EX_LEVEL_RANK[ex["level"]]
    if ex["equipment"] not in ctx.equipment or rank > ctx.max_rank or ex["id"] in ctx.excluded:
        return False
    if ex["id"] in PULLUP_FAMILY and rank > ctx.pull_cap:
        return False
    if ex["id"] == "muscle_up" and not (ctx.level == 3 and ctx.pullups_max >= 12):
        return False
    if ex["id"] in EASIER_VARIANTS and ctx.strong:
        return False
    return True


def _score(ex, ctx, role, order):
    rank = EX_LEVEL_RANK[ex["level"]]
    score = -abs(ctx.max_rank - rank) * 10
    weight = 2 if role in ("main", "secondary") else 1
    score += EQUIP_PRIORITY[ex["equipment"]] * weight
    # при равенстве: сильным — вариант посложнее (позже в списке), слабым — полегче
    score += (order / 1000.0) if ctx.strong else (-order / 1000.0)
    return score


def _pick(patterns, role, ctx, used, rotation):
    order = {ex["id"]: i for i, ex in enumerate(EXERCISES)}
    for pat in patterns:
        cands = [ex for ex in EXERCISES
                 if PATTERN.get(ex["id"]) == pat and _allowed(ex, ctx) and ex["id"] not in used]
        if cands:
            scored = sorted(((_score(ex, ctx, role, order[ex["id"]]), ex) for ex in cands),
                            key=lambda t: t[0], reverse=True)
            best = scored[0][0]
            top = [ex for sc, ex in scored if sc >= best - 5][:3]
            return top[rotation % len(top)]
    return None


def _round_to(x, step=2.5):
    return round(x / step) * step


def _prescribe(ex, role, ctx, intensity):
    """Подходы/повторы/отдых/подсказка для одного упражнения (базовая неделя)."""
    scheme = GOAL_SCHEME[ctx.goal]
    base_role = "accessory" if role in ("core", "skill") else role
    lo, hi, rest = scheme[base_role]
    sets = BASE_SETS[ctx.level][role]
    if ctx.goal == "maintenance":
        sets = max(2, sets - 1)
    unit = "повт."
    hint = None

    if role == "main" and intensity and ex["type"] == "weight":
        cfg = INTENSITY[intensity]
        if intensity == "heavy" and ex["equipment"] != "gym":
            cfg = INTENSITY["medium"]
        if cfg["reps"]:
            lo, hi = cfg["reps"]
            rest = cfg["rest"]

    if ex["id"] in HOLDS:
        lo, hi = HOLD_SECONDS[ctx.level]
        unit = "сек"
        rest = 45
    elif ex["id"] in SKILL_REPS:
        lo, hi = SKILL_REPS[ex["id"]]
        rest = max(rest, 120)
        if ex["id"] == "neg_pullups":
            hint = "Опускайся медленно: 3–5 секунд"
    elif ex["id"] in PULLUP_FAMILY and ctx.pullups_max > 0:
        target = max(3, round(ctx.pullups_max * 0.6))
        if target > 12 and ctx.goal != "endurance":
            lo, hi = 6, 10
            hint = "Добавь 5–10 кг на пояс"
        else:
            lo, hi = max(2, target - 1), target + 1
    elif ex["type"] == "reps" and role != "core":
        # упражнения с весом тела: диапазон выше, чем для штанги
        lo, hi = lo + 5, hi + 5
    elif role == "core":
        lo, hi = 10, 15

    return {"sets": sets, "lo": lo, "hi": hi, "unit": unit, "rest": rest, "hint": hint}


def _load_hint(ex, hi, rir, ctx, base_hint):
    if base_hint:
        return base_hint
    # рабочий вес от 1ПМ жима (формула Эпли): 1ПМ / (1 + (повторы + запас) / 30)
    if ex["id"] in BENCH_FACTORS and ctx.bench_max > 0:
        factor, suffix = BENCH_FACTORS[ex["id"]]
        w = _round_to(ctx.bench_max * factor / (1 + (hi + rir) / 30))
        if w > 0:
            return f"≈ {w:g} кг{suffix}"
    return None


def _fmt_range(lo, hi):
    return f"{lo}" if lo == hi else f"{lo}–{hi}"


# ===============================
# ГЛАВНАЯ ФУНКЦИЯ
# ===============================
def generate_program(profile):
    """Собрать 4-недельную программу. profile — dict из таблицы profile."""
    ctx = _Ctx(profile)
    split_key = choose_split(ctx.days, ctx.level)
    split_name, day_keys = SPLITS[split_key]

    # новичку больше 4 силовых в неделю не нужно — остальное восстановление
    strength_days = day_keys[:ctx.days]
    recovery_slots = ctx.days - len(strength_days)
    weekdays = SCHEDULE[ctx.days]

    # 1) базовая неделя: подбор упражнений
    base_days = []
    rotation_count = {}
    for i, key in enumerate(strength_days):
        name, focus, slots = DAY_TEMPLATES[key]
        occurrence = strength_days[:i].count(key)
        used, items = set(), []
        for role, patterns in slots:
            if role == "skill" and BASE_SETS[ctx.level]["skill"] == 0:
                continue
            slot_key = (role, tuple(patterns))
            rot = rotation_count.get(slot_key, 0)
            ex = _pick(patterns, role, ctx, used, rot)
            rotation_count[slot_key] = rot + 1
            if not ex:
                continue
            used.add(ex["id"])
            items.append((ex, role))
        for role, patterns in FILLERS:
            if len(items) >= MIN_EXERCISES:
                break
            ex = _pick(patterns, role, ctx, used, 0)
            if ex:
                used.add(ex["id"])
                items.append((ex, role))
        if occurrence:
            name = name.replace(" A", "").replace(" B", "") + f" ({occurrence + 1})"
        base_days.append({"name": name, "focus": focus, "items": items, "occurrence": occurrence})

    # волнообразная интенсивность: у Advanced/Pro основные упражнения
    # чередуют тяжёлые/средние/объёмные дни — по дням и по неделям
    if ctx.goal == "endurance" or ctx.level < 2:
        intensity_cycle = [None]
    elif ctx.level == 2:
        intensity_cycle = ["heavy", "medium"]
    else:
        intensity_cycle = ["heavy", "medium", "light"]

    # 2) четыре недели с прогрессией
    prog = PROGRESSION[ctx.level]
    weeks = []
    for w_index, (rir, delta, title, note) in enumerate(prog["weeks"], start=1):
        week_rir = 3 if delta == "deload" else rir
        days_out = []
        for d_index, day in enumerate(base_days):
            intensity = intensity_cycle[(d_index + day["occurrence"] + w_index - 1) % len(intensity_cycle)]
            if delta == "deload":
                intensity = "medium" if intensity else None
            exercises, minutes = [], 10
            for ex, role in day["items"]:
                p = _prescribe(ex, role, ctx, intensity)
                sets = p["sets"]
                if delta == "deload":
                    sets = max(1, round(sets * 0.6))
                elif delta and (role == "main" or (role == "secondary" and ctx.level == 3)):
                    sets += delta
                exercises.append({
                    "id": ex["id"], "name": ex["name"], "role": role,
                    "sets": sets, "reps": _fmt_range(p["lo"], p["hi"]), "unit": p["unit"],
                    "reps_lo": p["lo"], "rest": p["rest"],
                    "hint": _load_hint(ex, p["hi"], week_rir, ctx, p["hint"]),
                })
                minutes += sets * (0.75 + p["rest"] / 60)
            days_out.append({
                "index": d_index, "weekday": WEEKDAYS[weekdays[d_index]],
                "name": day["name"], "focus": day["focus"], "type": "strength",
                "intensity": INTENSITY[intensity]["label"] if intensity else None,
                "exercises": exercises, "minutes": int(round(minutes / 5) * 5),
                "finisher": FINISHER.get(ctx.goal),
            })
        for r in range(recovery_slots):
            idx = len(strength_days) + r
            days_out.append({"index": idx, "weekday": WEEKDAYS[weekdays[idx]],
                             "name": "Активное восстановление", "focus": "Лёгкое движение без нагрузки",
                             "type": "recovery", "intensity": None, "exercises": [],
                             "activities": RECOVERY_DAY, "minutes": 40, "finisher": None})
        weeks.append({"week": w_index, "title": title, "note": note, "rir": week_rir, "days": days_out})

    notes = list(ctx.injury_notes)
    if ctx.injury_notes:
        notes.append("При боли во время упражнения — остановись и покажись врачу.")
    if ctx.level == 0 and ctx.days > 4:
        notes.append("Новичку хватает 4 силовых тренировок в неделю — остальные дни отданы восстановлению.")
    if ctx.pullups_max == 0 and ctx.level >= 1:
        notes.append("Укажи максимум подтягиваний в профиле — программа точнее подберёт нагрузку.")
    if ctx.equipment == ["bodyweight"]:
        notes.append("Программа только с весом тела. Добавь гантели или резину в настройках — станет разнообразнее.")

    minutes = [d["minutes"] for d in weeks[0]["days"] if d["type"] == "strength"]
    return {
        "version": 1,
        "generated_on": date.today().isoformat(),
        "summary": {
            "level": LEVELS[ctx.level], "level_label": LEVEL_LABELS[LEVELS[ctx.level]],
            "goal": ctx.goal, "days_per_week": ctx.days, "split": split_name,
            "progression": prog["model"], "equipment": ctx.equipment,
            "session_minutes": (_fmt_range(min(minutes), max(minutes)) if minutes else "—"),
            "strength_days": len(strength_days),
        },
        "notes": notes,
        "progression_rules": prog["rules"],
        "warmup": WARMUP,
        "cooldown": COOLDOWN,
        "weeks": weeks,
    }


def next_session(plan, sessions_done):
    """Какая тренировка следующая — по числу дней с записями после создания плана."""
    strength = [d for d in plan["weeks"][0]["days"] if d["type"] == "strength"]
    if not strength:
        return None
    per_week = len(strength)
    week = min(4, sessions_done // per_week + 1)
    cycle_done = sessions_done >= per_week * 4
    day_idx = sessions_done % per_week
    day = [d for d in plan["weeks"][week - 1]["days"] if d["type"] == "strength"][day_idx]
    return {"week": week, "day_index": day["index"], "day": day,
            "sessions_done": sessions_done, "cycle_complete": cycle_done}
