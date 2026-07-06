/* =========================================================
   trAIned — ОБЩИЕ ПОМОЩНИКИ (+ авторизация)
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

/* ---------- АВТОРИЗАЦИЯ ---------- */
function getToken(){ return localStorage.getItem('trained_token'); }
function setToken(t){ localStorage.setItem('trained_token', t); }
function clearToken(){ localStorage.removeItem('trained_token'); }
function authHeaders(){
  const t = getToken();
  return t ? { 'Authorization': 'Bearer ' + t } : {};
}

// охрана страниц: без токена — на страницу входа (кроме самой login.html)
(function(){
  const onLogin = location.pathname.endsWith('/login.html');
  if(!onLogin && !getToken()){
    location.replace('/login.html');
  }
})();

// кнопка «Выйти» добавляется в шапку автоматически
document.addEventListener('DOMContentLoaded', ()=>{
  const right = document.querySelector('.top-right');
  if(right && getToken()){
    const b = document.createElement('button');
    b.className = 'tab';
    b.textContent = 'Выйти';
    b.style.cursor = 'pointer';
    b.title = 'Выйти из аккаунта';
    b.addEventListener('click', async ()=>{
      try{ await apiPost('/api/auth/logout', null); }catch(e){}
      clearToken();
      location.replace('/login.html');
    });
    right.appendChild(b);
  }
});

/* ---------- УВЕДОМЛЕНИЕ ---------- */
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

/* ---------- ОБЁРТКИ ДЛЯ API ---------- */
async function handleResponse(res){
  if(res.status === 401 && !location.pathname.endsWith('/login.html')){
    clearToken();
    location.replace('/login.html');
    throw new Error('Требуется вход');
  }
  if(!res.ok){
    const err = await res.json().catch(() => ({}));
    const msg = typeof err.detail === 'string' ? err.detail
              : err.detail ? JSON.stringify(err.detail)
              : 'HTTP ' + res.status;
    throw new Error(msg);
  }
  return res.json();
}

async function apiGet(path){
  const res = await fetch(path, { headers: authHeaders() });
  return handleResponse(res);
}

async function apiPost(path, body){
  const res = await fetch(path, {
    method: 'POST',
    headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
    body: body ? JSON.stringify(body) : undefined
  });
  return handleResponse(res);
}

async function apiDelete(path){
  const res = await fetch(path, { method: 'DELETE', headers: authHeaders() });
  return handleResponse(res);
}