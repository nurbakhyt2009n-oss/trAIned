/* =========================================================
   trAIned — ОБЩИЕ ПОМОЩНИКИ
   Подключается на каждой странице ПЕРЕД её собственным скриптом.
   ========================================================= */

// короткие селекторы
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// словари для красивых русских подписей
const GOAL_LABELS = {
  muscle_gain:   "Набор массы",
  fat_loss:      "Снижение веса",
  recomposition: "Рекомпозиция",
  maintenance:   "Поддержание",
  endurance:     "Выносливость"
};
const EXP_LABELS = {
  Beginner:     "Новичок",
  Intermediate: "Средний",
  Advanced:     "Продвинутый"
};
const ACTIVITY_LABELS = {
  sedentary:   "Сидячий",
  light:       "Лёгкая",
  moderate:    "Умеренная",
  active:      "Высокая",
  very_active: "Очень высокая"
};

// всплывающее уведомление — само создаёт элемент, если его нет на странице
function showToast(msg){
  let t = document.getElementById('toast');
  if(!t){
    t = document.createElement('div');
    t.id = 'toast';
    t.className = 'toast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 2800);
}

// ---------- обёртки для запросов к API ----------
// Бросают ошибку, если сервер ответил не ОК — её удобно ловить через try/catch.
async function apiGet(path){
  const res = await fetch(path);
  if(!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

async function apiPost(path, body){
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  });
  if(!res.ok){
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ? JSON.stringify(err.detail) : 'HTTP ' + res.status);
  }
  return res.json();
}

async function apiDelete(path){
  const res = await fetch(path, { method: 'DELETE' });
  if(!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}