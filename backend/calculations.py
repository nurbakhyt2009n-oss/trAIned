# ===============================
# РАСЧЁТ КАЛОРИЙ И КБЖУ
# Формула Миффлина-Сан Жеора
# ===============================

def calculate_bmr(weight, height, age, gender):
    """
    Базовый обмен веществ (BMR)
    weight — кг, height — см, age — лет
    """
    if gender == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161
    return round(bmr)


def calculate_tdee(bmr, activity_level):
    """
    Суточная норма калорий с учётом активности (TDEE)
    """
    multipliers = {
        "sedentary":     1.2,   # сидячий образ жизни
        "light":         1.375, # лёгкая активность 1-3 дня
        "moderate":      1.55,  # умеренная 3-5 дней
        "active":        1.725, # высокая 6-7 дней
        "very_active":   1.9    # очень высокая + физ. работа
    }
    multiplier = multipliers.get(activity_level, 1.55)
    return round(bmr * multiplier)


def calculate_target_calories(tdee, goal):
    """
    Целевые калории в зависимости от цели
    """
    goals = {
        "muscle_gain":   tdee + 300,   # профицит
        "fat_loss":      tdee - 500,   # дефицит
        "recomposition": tdee,         # поддержание
        "maintenance":   tdee,         # поддержание
        "endurance":     tdee + 100    # лёгкий профицит
    }
    return goals.get(goal, tdee)


def calculate_macros(target_calories, weight, goal):
    """
    Расчёт БЖУ (белки, жиры, углеводы)
    Возвращает граммы
    """
    if goal == "muscle_gain":
        protein = weight * 2.2      # 2.2г на кг
        fat = weight * 1.0          # 1г на кг
    elif goal == "fat_loss":
        protein = weight * 2.5      # больше белка при сушке
        fat = weight * 0.8
    else:
        protein = weight * 2.0
        fat = weight * 1.0

    protein_cal = protein * 4
    fat_cal = fat * 9
    carb_cal = target_calories - protein_cal - fat_cal
    carbs = max(carb_cal / 4, 50)   # минимум 50г углеводов

    return {
        "protein": round(protein),
        "fat": round(fat),
        "carbs": round(carbs)
    }


def calculate_water(weight, activity_level):
    """
    Норма воды в литрах
    """
    base = weight * 0.033
    if activity_level in ["active", "very_active"]:
        base += 0.5
    return round(base, 1)


def get_full_nutrition_plan(weight, height, age, gender, activity_level, goal):
    """
    Полный расчёт — одна функция для всего
    """
    bmr = calculate_bmr(weight, height, age, gender)
    tdee = calculate_tdee(bmr, activity_level)
    target_calories = calculate_target_calories(tdee, goal)
    macros = calculate_macros(target_calories, weight, goal)
    water = calculate_water(weight, activity_level)

    return {
        "bmr": bmr,
        "tdee": tdee,
        "target_calories": target_calories,
        "protein": macros["protein"],
        "fat": macros["fat"],
        "carbs": macros["carbs"],
        "water": water
    }


# ===============================
# ТЕСТ — запусти python calculations.py
# ===============================
if __name__ == "__main__":
    # Твои данные как пример
    result = get_full_nutrition_plan(
        weight=54,
        height=170,
        age=18,
        gender="male",
        activity_level="active",
        goal="muscle_gain"
    )

    print("📊 Твой план питания:")
    print(f"  BMR (базовый обмен):     {result['bmr']} ккал")
    print(f"  TDEE (с активностью):    {result['tdee']} ккал")
    print(f"  Цель (профицит):         {result['target_calories']} ккал")
    print(f"  Белки:                   {result['protein']} г")
    print(f"  Жиры:                    {result['fat']} г")
    print(f"  Углеводы:                {result['carbs']} г")
    print(f"  Вода:                    {result['water']} л")