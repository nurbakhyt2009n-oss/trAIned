# ===============================
# IMPORTS
# ===============================
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
 
# ===============================
# PAGE CONFIG
# ===============================
st.set_page_config(
    page_title="trAIned AI Coach",
    layout="wide",
    initial_sidebar_state="collapsed"
)
 
from dotenv import load_dotenv
import os
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
 
# ===============================
# CUSTOM CSS
# ===============================
st.markdown("""
<style>
.main { background-color: #0e1117; }
.stApp {
    background: linear-gradient(to bottom right, #0e1117, #111827);
    color: white;
}
h1, h2, h3 { color: white; }
[data-testid="stMetric"] {
    background-color: #1f2937;
    padding: 20px;
    border-radius: 15px;
    border: 1px solid #374151;
}
.stButton > button {
    width: 100%;
    border-radius: 12px;
    height: 3em;
    font-size: 16px;
    font-weight: bold;
    background-color: #2563eb;
    color: white;
    border: none;
}
.stButton > button:hover { background-color: #1d4ed8; }
section[data-testid="stSidebar"] { background-color: #111827; }
</style>
""", unsafe_allow_html=True)
 
# ===============================
# SESSION STATE
import os

DATA_FILE = "training_data.csv"

if "data" not in st.session_state:
    if os.path.exists(DATA_FILE):
        st.session_state.data = pd.read_csv(DATA_FILE)
    else:
        st.session_state.data = pd.DataFrame(
            columns=["day", "sleep_hours", "fatigue", "weight"]
        )
 
if "profile" not in st.session_state:
    st.session_state.profile = {
        "name": "Атлет",
        "goal": "Muscle gain",
        "experience": "Intermediate",
        "weight": "52-56",
        "pullups": 20,
        "bench": 75
    }
 
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
 
# ===============================
# РЕАЛЬНЫЙ AI КОУЧ (GPT)
# ===============================
def ai_coach_reply(user_message, data, profile):
 
    # Формируем контекст с данными атлета
    athlete_context = f"""
Ты — персональный AI-тренер для молодого атлета.
 
Профиль атлета:
- Имя: {profile.get('name', 'Атлет')}
- Цель: {profile.get('goal', 'Набор мышц')}
- Уровень: {profile.get('experience', 'Intermediate')}
- Вес тела: {profile.get('weight', '52-56')} кг
- Максимум подтягиваний: {profile.get('pullups', 20)} раз
- Жим лёжа 1ПМ: {profile.get('bench', 75)} кг
- Тренировочный стаж: 3 года
 
Текущие данные (последняя запись):
"""
 
    if len(data) > 0:
        last = data.iloc[-1]
        athlete_context += f"""
- День тренировки: {last['day']}
- Сон: {last['sleep_hours']} часов
- Усталость: {last['fatigue']}/10
- Вес: {last['weight']} кг
"""
        if len(data) >= 3:
            recent = data.tail(7)
            athlete_context += f"""
Средние показатели за последние {len(recent)} дней:
- Средний сон: {recent['sleep_hours'].mean():.1f} часов
- Средняя усталость: {recent['fatigue'].mean():.1f}/10
"""
    else:
        athlete_context += "- Данных пока нет, попроси атлета внести первую запись.\n"
 
    athlete_context += """
Правила:
- Отвечай на русском языке
- Давай конкретные, практические советы
- Учитывай текущее состояние (сон, усталость) при рекомендациях
- Ты не врач — не ставь диагнозы, при болях отправляй к специалисту
- Будь как опытный тренер — прямо, по делу, с поддержкой
"""
 
    # Собираем историю сообщений для GPT
    messages = [{"role": "system", "content": athlete_context}]
 
    # Добавляем последние 10 сообщений из истории (память чата)
    for msg in st.session_state.chat_history[-10:]:
        role = "user" if msg["role"] == "user" else "assistant"
        messages.append({"role": role, "content": msg["content"]})
 
    # Добавляем текущее сообщение
    messages.append({"role": "user", "content": user_message})
 
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",   
            messages=messages,
            max_tokens=500,
            temperature=0.7
        )
        return response.choices[0].message.content
 
    except Exception as e:
        return f"Ошибка подключения к AI: {str(e)}"
 
 
# ===============================
# SIDEBAR ПРОФИЛЬ
# ===============================
st.sidebar.header("👤 Профиль атлета")
 
name = st.sidebar.text_input("Имя", value=st.session_state.profile.get("name", ""))
 
goal = st.sidebar.selectbox(
    "Цель тренировок",
    ["Muscle gain", "Strength", "Health", "Fat loss"],
    index=0
)
 
experience = st.sidebar.selectbox(
    "Уровень",
    ["Beginner", "Intermediate", "Advanced"],
    index=1
)
 
pullups = st.sidebar.number_input(
    "Макс. подтягиваний (раз)",
    min_value=0,
    max_value=100,
    value=int(st.session_state.profile.get("pullups", 20))
)
 
bench = st.sidebar.number_input(
    "Жим лёжа 1ПМ (кг)",
    min_value=0,
    max_value=300,
    value=int(st.session_state.profile.get("bench", 75))
)
 
if st.sidebar.button("💾 Сохранить профиль"):
    st.session_state.profile = {
        "name": name,
        "goal": goal,
        "experience": experience,
        "pullups": pullups,
        "bench": bench,
        "weight": "52-56"
    }
    st.sidebar.success("Профиль сохранён ✅")
 
 
# ===============================
# ЗАГОЛОВОК
# ===============================
st.title("💪 trAIned — AI Фитнес-тренер")
st.markdown("### Умные советы на основе твоих реальных данных")
st.caption("GPT-4o-mini · Персональный коучинг · Анализ восстановления")
 
# ===============================
# AI ЧАТ
# ===============================
st.header("🤖 AI Тренер")
 
# Показываем историю чата
chat_container = st.container()
with chat_container:
    if len(st.session_state.chat_history) == 0:
        st.info("👋 Привет! Спроси меня про тренировку, восстановление, питание или прогресс.")
 
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            st.markdown(f"🧑 **Ты:** {msg['content']}")
        else:
            st.markdown(f"🤖 **Тренер:** {msg['content']}")
 
# Инпут
col1, col2 = st.columns([4, 1])
 
with col1:
    user_input = st.text_input(
        "Спроси про тренировку, сон, восстановление...",
        key="chat_input",
        placeholder="Например: могу я сегодня тренироваться интенсивно?"
    )
 
with col2:
    send = st.button("Отправить", key="send_chat")
 
if send and user_input:
    st.session_state.chat_history.append(
        {"role": "user", "content": user_input}
    )
 
    with st.spinner("Тренер думает..."):
        reply = ai_coach_reply(
            user_input,
            st.session_state.data,
            st.session_state.profile
        )
 
    st.session_state.chat_history.append(
        {"role": "assistant", "content": reply}
    )
    st.rerun()
 
if st.button("🗑️ Очистить чат", key="clear_chat"):
    st.session_state.chat_history = []
    st.rerun()
 
 
# ===============================
# ВВОД ДАННЫХ
# ===============================
with st.expander("📥 Записать данные за день", expanded=False):
 
    day = st.number_input("День тренировки", min_value=1, step=1)
 
    sleep_hours = st.number_input(
        "Часов сна", min_value=0.0, max_value=12.0, step=0.5
    )
 
    fatigue = st.slider("Усталость (1 = свежий, 10 = выжат)", 1, 10, 5)
 
    weight = st.number_input(
        "Вес тела (кг)", min_value=30.0, max_value=200.0, step=0.5, value=54.0
    )
 
    if st.button("➕ Сохранить", key="save_data"):
        new_row = pd.DataFrame(
            [[day, sleep_hours, fatigue, weight]],
            columns=["day", "sleep_hours", "fatigue", "weight"]
        )
        st.session_state.data = pd.concat(
            [st.session_state.data, new_row], ignore_index=True
        )
        st.session_state.data.to_csv(DATA_FILE, index=False)
        st.success("✅ Данные сохранены")
 
 
# ===============================
# ЖУРНАЛ ТРЕНИРОВОК
# ===============================
st.header("📊 Журнал тренировок")
 
if len(st.session_state.data) > 0:
    st.dataframe(st.session_state.data, use_container_width=True)
else:
    st.info("Данных пока нет. Внеси первую запись выше.")
 
 
# ===============================
# WELLBEING SCORE
# ===============================
st.header("🧠 Состояние сегодня")
 
if len(st.session_state.data) > 0:
    last = st.session_state.data.iloc[-1]
 
    wellbeing_score = int(
        last["sleep_hours"] * 10 - last["fatigue"] * 7 + 40
    )
    wellbeing_score = max(0, min(100, wellbeing_score))
 
    col1, col2, col3 = st.columns(3)
 
    with col1:
        st.metric("Recovery Score", f"{wellbeing_score}/100")
    with col2:
        st.metric("Усталость", f"{last['fatigue']}/10")
    with col3:
        st.metric("Сон", f"{last['sleep_hours']} ч")
 
    if wellbeing_score >= 75:
        st.success("🟢 Отличное восстановление. Можно тренироваться интенсивно.")
    elif wellbeing_score >= 50:
        st.warning("🟡 Среднее состояние. Контролируй интенсивность.")
    else:
        st.error("🔴 Плохое восстановление. Приоритет — сон и отдых.")
else:
    st.info("Внеси данные чтобы увидеть анализ.")
 
 
# ===============================
# ТРЕНД ВОССТАНОВЛЕНИЯ
# ===============================
st.header("📈 Тренд за неделю")
 
if len(st.session_state.data) >= 3:
    recent = st.session_state.data.tail(7)
    avg_sleep = recent["sleep_hours"].mean()
    avg_fatigue = recent["fatigue"].mean()
 
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Средний сон", f"{avg_sleep:.1f} ч")
    with col2:
        st.metric("Средняя усталость", f"{avg_fatigue:.1f}/10")
 
    if avg_sleep >= 7 and avg_fatigue <= 4:
        st.success("🟢 Позитивный тренд восстановления.")
    elif avg_sleep < 6 and avg_fatigue >= 6:
        st.error("🔴 Признаки перетренированности. Нужен отдых.")
    else:
        st.warning("🟡 Смешанные сигналы восстановления.")
else:
    st.info("Нужно минимум 3 дня данных.")
 
 
# ===============================
# ГРАФИК ВЕСА (баги исправлены)
# ===============================
if len(st.session_state.data) > 1:
    st.header("📊 Прогресс веса тела")
 
    fig, ax = plt.subplots(figsize=(10, 4))
 
    fig.patch.set_facecolor("#111827")
    ax.set_facecolor("#1f2937")
 
    ax.plot(
        st.session_state.data["day"],
        st.session_state.data["weight"],
        marker="o",
        linewidth=3,
        color="#2563eb",
        markerfacecolor="white",
        markersize=8
    )
 
    ax.set_xlabel("День тренировки", color="white")
    ax.set_ylabel("Вес (кг)", color="white")
    ax.set_title("Динамика веса", color="white")
    ax.tick_params(colors="white")
    ax.grid(alpha=0.2, color="white")
 
    for spine in ax.spines.values():
        spine.set_edgecolor("#374151")
 
    st.pyplot(fig)
    plt.close(fig)
 
 
# ===============================
# СБРОС ДАННЫХ
# ===============================
st.divider()
st.subheader("⚠️ Управление данными")
 
if st.button("🗑️ Сбросить все данные тренировок", key="reset_data"):
    st.session_state.data = pd.DataFrame(
        columns=["day", "sleep_hours", "fatigue", "weight"]
    )
    st.success("Данные очищены.")
 
 
# ===============================
# ОГРАНИЧЕНИЯ
# ===============================
st.header("⚠️ Важно")
st.markdown("""
- Это AI-ассистент, не медицинский специалист
- При болях или травмах — обратись к врачу
- Данные хранятся только в текущей сессии
""")
 