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
  Advanced:     "Продвинутый",
  Pro:          "Профи"
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

// кнопки «Аккаунт» и «Выйти» добавляются в шапку автоматически
document.addEventListener('DOMContentLoaded', ()=>{
  const right = document.querySelector('.top-right');
  if(right && getToken()){
    const acc = document.createElement('button');
    acc.className = 'tab';
    acc.textContent = 'Аккаунт';
    acc.style.cursor = 'pointer';
    acc.addEventListener('click', openAccountDialog);
    right.appendChild(acc);

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

/* ---------- АККАУНТ: смена пароля, выход со всех устройств ---------- */
function openAccountDialog(){
  if(document.getElementById('accDialog')) return;
  const wrap = document.createElement('div');
  wrap.id = 'accDialog';
  wrap.style.cssText = 'position:fixed; inset:0; z-index:60; display:grid; place-items:center; padding:16px; background:rgba(10,9,7,.7); backdrop-filter:blur(8px);';
  wrap.innerHTML =
    '<div class="card" style="width:100%; max-width:420px; padding:28px;">' +
      '<div class="card-title"><h2>Аккаунт</h2></div>' +
      '<p class="muted" id="accUser" style="margin-top:-8px;"></p>' +
      '<div class="field section-gap"><span class="label">Текущий пароль</span><input class="input" type="password" id="accOld" autocomplete="current-password"></div>' +
      '<div class="field section-gap"><span class="label">Новый пароль</span><input class="input" type="password" id="accNew" autocomplete="new-password" placeholder="минимум 8 символов, буквы и цифры"></div>' +
      '<div class="field section-gap"><span class="label">Повтори новый пароль</span><input class="input" type="password" id="accNew2" autocomplete="new-password"></div>' +
      '<p id="accMsg" style="display:none; margin-top:14px; font-size:13px;"></p>' +
      '<div style="display:flex; gap:10px; margin-top:20px; flex-wrap:wrap;">' +
        '<button class="btn" id="accSave">Сменить пароль</button>' +
        '<button class="btn btn-ghost" id="accClose">Закрыть</button>' +
      '</div>' +
      '<button class="tab" id="accAll" style="margin-top:18px; padding-left:0; cursor:pointer;">Выйти на всех устройствах</button>' +
    '</div>';
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  const msg = (text, ok) => {
    const m = document.getElementById('accMsg');
    m.textContent = text; m.style.display = 'block';
    m.style.color = ok ? 'var(--good)' : 'var(--bad)';
  };
  wrap.addEventListener('click', e => { if(e.target === wrap) close(); });
  document.getElementById('accClose').addEventListener('click', close);
  apiGet('/api/auth/me').then(d => {
    document.getElementById('accUser').textContent = 'Логин: ' + (d.username || '—');
  }).catch(()=>{});

  document.getElementById('accSave').addEventListener('click', async (e)=>{
    const oldP = document.getElementById('accOld').value;
    const newP = document.getElementById('accNew').value;
    if(!oldP || !newP) return msg('Заполни оба пароля');
    if(newP.length < 8) return msg('Новый пароль — минимум 8 символов');
    if(!/[A-Za-zА-Яа-яЁё]/.test(newP) || !/\d/.test(newP)) return msg('Нужны буквы и цифры');
    if(newP !== document.getElementById('accNew2').value) return msg('Пароли не совпадают');
    e.target.disabled = true;
    try{
      await apiPost('/api/auth/change-password', { current_password: oldP, new_password: newP });
      msg('Пароль изменён. На других устройствах нужно войти заново.', true);
      ['accOld','accNew','accNew2'].forEach(id => document.getElementById(id).value = '');
    }catch(err){
      msg(err.message);
    }finally{
      e.target.disabled = false;
    }
  });

  document.getElementById('accAll').addEventListener('click', async ()=>{
    try{ await apiPost('/api/auth/logout-all', null); }catch(e){}
    clearToken();
    location.replace('/login.html');
  });
}

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