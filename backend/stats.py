# ===============================
# СТАТИСТИКА ИСПОЛЬЗОВАНИЯ
# Считает реальные цифры по базе: пользователи, активность, тренировки, питание.
# Используется скриптом scripts/backup.py и закрытым эндпоинтом /api/admin/stats.
# Только агрегаты — никаких логинов, имён и паролей.
# ===============================
import csv
import io
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from html import escape

# таблицы для бэкапа; колонки, которые никогда не выгружаем
BACKUP_TABLES = ["users", "profile", "training_plan", "training_log",
                 "workout_log", "nutrition_log", "chat_history", "user_visits"]
SKIP_COLUMNS = {"users": {"password_hash"}}

LABELS_EN = {
    "muscle_gain": "Muscle gain", "fat_loss": "Fat loss", "recomposition": "Recomposition",
    "maintenance": "Maintenance", "endurance": "Endurance",
    "Beginner": "Beginner", "Intermediate": "Intermediate", "Advanced": "Advanced", "Pro": "Pro / athlete",
}


def _rows(conn, sql):
    """Безопасный SELECT: если таблицы нет (старая база) — пустой список."""
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def _day(value):
    """TIMESTAMP из SQLite (строка) или Postgres (datetime) -> 'YYYY-MM-DD'."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value)
    return s[:10] if len(s) >= 10 else None


def _week(day_str):
    d = date.fromisoformat(day_str)
    return (d - timedelta(days=d.weekday())).isoformat()


def _num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def compute_stats(conn, today=None):
    today = today or date.today()
    users = _rows(conn, "SELECT id, created_at FROM users")
    profiles = _rows(conn, "SELECT user_id, goal, experience, days_per_week FROM profile")
    workouts = _rows(conn, "SELECT user_id, date, exercise_name, sets, reps, weight, logged_at FROM workout_log")
    meals = _rows(conn, "SELECT user_id, date, calories, logged_at FROM nutrition_log")
    checkins = _rows(conn, "SELECT user_id, logged_at FROM training_log")
    chats = _rows(conn, "SELECT user_id, role, created_at FROM chat_history")
    plans = _rows(conn, "SELECT user_id FROM training_plan")
    visits = _rows(conn, "SELECT user_id, day FROM user_visits")

    # --- активность: (пользователь, день) по всем действиям ---
    activity = defaultdict(set)          # user_id -> {days}
    for r in workouts:
        d = r.get("date") or _day(r.get("logged_at"))
        if d: activity[r["user_id"]].add(d)
    for r in meals:
        d = r.get("date") or _day(r.get("logged_at"))
        if d: activity[r["user_id"]].add(d)
    for r in checkins:
        d = _day(r.get("logged_at"))
        if d: activity[r["user_id"]].add(d)
    for r in visits:
        if r.get("day"): activity[r["user_id"]].add(r["day"])
    for r in chats:
        if r.get("role") == "user":
            d = _day(r.get("created_at"))
            if d: activity[r["user_id"]].add(d)
    activity = {u: days for u, days in activity.items() if u is not None}

    all_days = sorted({d for days in activity.values() for d in days})
    since7 = (today - timedelta(days=6)).isoformat()
    since30 = (today - timedelta(days=29)).isoformat()

    # --- тренировки ---
    sessions = {(r["user_id"], r.get("date")) for r in workouts if r.get("date")}
    total_sets = sum(int(r.get("sets") or 0) for r in workouts)
    total_reps = sum(int(r.get("sets") or 0) * int(r.get("reps") or 0) for r in workouts)
    volume = sum(int(r.get("sets") or 0) * int(r.get("reps") or 0) * _num(r.get("weight")) for r in workouts)
    top_ex = Counter(r.get("exercise_name") for r in workouts if r.get("exercise_name")).most_common(10)

    # --- по неделям ---
    signups_w = Counter(_week(d) for d in (_day(u.get("created_at")) for u in users) if d)
    wau = defaultdict(set)
    for u, days in activity.items():
        for d in days:
            wau[_week(d)].add(u)
    sets_w = Counter()
    for r in workouts:
        if r.get("date"):
            sets_w[_week(r["date"])] += int(r.get("sets") or 0)
    weeks = sorted(set(signups_w) | set(wau) | set(sets_w))
    if weeks:  # непрерывный ряд недель без пропусков
        start, end = date.fromisoformat(weeks[0]), date.fromisoformat(weeks[-1])
        weeks, cur = [], start
        while cur <= end:
            weeks.append(cur.isoformat()); cur += timedelta(days=7)
    cumulative, total = [], 0
    for w in weeks:
        total += signups_w.get(w, 0)
        cumulative.append(total)

    days_per_user = sorted(len(d) for d in activity.values())
    median_days = days_per_user[len(days_per_user) // 2] if days_per_user else 0

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period": {"first_activity": all_days[0] if all_days else None,
                   "last_activity": all_days[-1] if all_days else None},
        "users": {
            "registered": len(users),
            "completed_onboarding": len({p["user_id"] for p in profiles if p.get("user_id") is not None}),
            "with_training_plan": len({p["user_id"] for p in plans}),
            "active_ever": len(activity),
            "returned_2plus_days": sum(1 for d in activity.values() if len(d) >= 2),
            "active_7plus_days": sum(1 for d in activity.values() if len(d) >= 7),
            "active_last_7_days": sum(1 for d in activity.values() if any(x >= since7 for x in d)),
            "active_last_30_days": sum(1 for d in activity.values() if any(x >= since30 for x in d)),
            "median_active_days": median_days,
            "visit_tracking_since": min((r["day"] for r in visits if r.get("day")), default=None),
        },
        "training": {
            "exercise_entries": len(workouts),
            "workout_sessions": len(sessions),
            "sets_logged": total_sets,
            "reps_logged": total_reps,
            "volume_kg": round(volume),
            "top_exercises": [{"name": n, "entries": c} for n, c in top_ex],
        },
        "nutrition": {
            "meals_logged": len(meals),
            "calories_tracked": round(sum(_num(r.get("calories")) for r in meals)),
        },
        "recovery": {"checkins": len(checkins)},
        "ai_coach": {
            "user_messages": sum(1 for r in chats if r.get("role") == "user"),
            "coach_replies": sum(1 for r in chats if r.get("role") == "assistant"),
        },
        "segments": {
            "goals": dict(Counter(p.get("goal") or "—" for p in profiles).most_common()),
            "levels": dict(Counter(p.get("experience") or "—" for p in profiles).most_common()),
        },
        "weekly": [{"week": w, "signups": signups_w.get(w, 0), "total_users": c,
                    "active_users": len(wau.get(w, ())), "sets_logged": sets_w.get(w, 0)}
                   for w, c in zip(weeks, cumulative)],
    }


# ===============================
# HTML-ОТЧЁТ (без внешних библиотек, графики — inline SVG)
# ===============================
def _bar_chart(points, key, label):
    if not points:
        return "<p class='muted'>No data yet</p>"
    w, h, pad_l, pad_b = 720, 220, 36, 28
    n = len(points)
    vmax = max(max(p[key] for p in points), 1)
    bw = (w - pad_l) / n
    bars, labels = [], []
    step = max(1, n // 8)
    for i, p in enumerate(points):
        bh = (h - pad_b - 10) * p[key] / vmax
        x = pad_l + i * bw
        bars.append(f"<rect x='{x + bw * 0.15:.1f}' y='{h - pad_b - bh:.1f}' width='{bw * 0.7:.1f}' "
                    f"height='{bh:.1f}' rx='2'><title>{escape(p['week'])}: {p[key]}</title></rect>")
        if i % step == 0:
            labels.append(f"<text x='{x + bw / 2:.1f}' y='{h - 8}' text-anchor='middle'>{p['week'][5:]}</text>")
    grid = (f"<text x='{pad_l - 6}' y='16' text-anchor='end'>{vmax:g}</text>"
            f"<text x='{pad_l - 6}' y='{h - pad_b}' text-anchor='end'>0</text>"
            f"<line x1='{pad_l}' y1='{h - pad_b}' x2='{w}' y2='{h - pad_b}' class='axis'/>")
    return (f"<figure><figcaption>{escape(label)}</figcaption>"
            f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='{escape(label)}'>{grid}"
            f"<g class='bars'>{''.join(bars)}</g><g class='lbl'>{''.join(labels)}</g></svg></figure>")


def render_report_html(s):
    u, t, n = s["users"], s["training"], s["nutrition"]
    kpis = [
        ("Registered users", u["registered"]), ("Completed onboarding", u["completed_onboarding"]),
        ("Active users (1+ entry)", u["active_ever"]), ("Came back on 2+ days", u["returned_2plus_days"]),
        ("Active on 7+ days", u["active_7plus_days"]), ("Active in last 30 days", u["active_last_30_days"]),
        ("Workout sessions", t["workout_sessions"]), ("Sets logged", t["sets_logged"]),
        ("Reps logged", t["reps_logged"]), ("Total volume lifted, kg", t["volume_kg"]),
        ("Meals logged", n["meals_logged"]), ("Recovery check-ins", s["recovery"]["checkins"]),
        ("Questions to AI coach", s["ai_coach"]["user_messages"]), ("Training plans generated", u["with_training_plan"]),
    ]
    tiles = "".join(f"<div class='tile'><div class='v'>{v:,}</div>".replace(",", " ") +
                    f"<div class='k'>{escape(k)}</div></div>" for k, v in kpis)
    top = "".join(f"<tr><td>{escape(x['name'])}</td><td>{x['entries']}</td></tr>" for x in t["top_exercises"])
    segs = lambda d: "".join(f"<tr><td>{escape(LABELS_EN.get(k, str(k)))}</td><td>{v}</td></tr>"
                             for k, v in d.items())
    weekly = "".join(f"<tr><td>{w['week']}</td><td>{w['signups']}</td><td>{w['total_users']}</td>"
                     f"<td>{w['active_users']}</td><td>{w['sets_logged']}</td></tr>" for w in s["weekly"])
    period = s["period"]
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>trAIned · Usage report</title>
<style>
:root{{ --bg:#0F0E0B; --surface:#1A1712; --line:rgba(231,222,200,.12); --text:#F4EFE4; --dim:#B9B0A0; --mute:#8A8175; --accent:#C8A86A; }}
@media (prefers-color-scheme: light){{ :root{{ --bg:#FAF7F0; --surface:#FFFFFF; --line:rgba(40,30,10,.12); --text:#1E1A12; --dim:#4A4336; --mute:#7A715F; --accent:#8F713F; }} }}
*{{ box-sizing:border-box; margin:0; padding:0; }}
body{{ font-family:system-ui,-apple-system,Segoe UI,sans-serif; background:var(--bg); color:var(--text); padding:32px 16px; line-height:1.5; }}
main{{ max-width:960px; margin:0 auto; }}
h1{{ font-size:28px; letter-spacing:-.02em; }} h2{{ font-size:17px; margin:36px 0 14px; }}
.sub{{ color:var(--mute); font-size:14px; margin-top:6px; }}
.tiles{{ display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:12px; margin-top:24px; }}
.tile{{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px; }}
.tile .v{{ font-size:26px; font-variant-numeric:tabular-nums; color:var(--accent); font-weight:600; }}
.tile .k{{ font-size:12px; color:var(--dim); margin-top:4px; }}
figure{{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px; margin-top:12px; }}
figcaption{{ font-size:13px; color:var(--dim); margin-bottom:8px; }}
svg{{ width:100%; height:auto; display:block; }} .bars rect{{ fill:var(--accent); }}
svg text{{ fill:var(--mute); font-size:11px; }} .axis{{ stroke:var(--line); }}
.cols{{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
table{{ width:100%; border-collapse:collapse; font-size:14px; background:var(--surface); border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
th,td{{ text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); }} th{{ color:var(--mute); font-weight:500; font-size:12px; }}
td:not(:first-child),th:not(:first-child){{ text-align:right; font-variant-numeric:tabular-nums; }}
.wrap-table{{ overflow-x:auto; }} .muted{{ color:var(--mute); font-size:14px; }}
footer{{ margin-top:36px; color:var(--mute); font-size:12px; }}
@media (max-width:640px){{ .cols{{ grid-template-columns:1fr; }} }}
</style></head><body><main>
<h1>trAIned — usage report</h1>
<p class="sub">Activity from {period['first_activity'] or '—'} to {period['last_activity'] or '—'} · generated {s['generated_at'].replace('T', ' ')}</p>
<div class="tiles">{tiles}</div>
<h2>Growth and weekly activity</h2>
{_bar_chart(s['weekly'], 'total_users', 'Total users (cumulative)')}
{_bar_chart(s['weekly'], 'active_users', 'Weekly active users')}
{_bar_chart(s['weekly'], 'sets_logged', 'Sets logged per week')}
<div class="cols">
<div><h2>Most logged exercises</h2><table><tr><th>Exercise</th><th>Entries</th></tr>{top or '<tr><td>—</td><td>0</td></tr>'}</table></div>
<div><h2>User goals</h2><table><tr><th>Goal</th><th>Users</th></tr>{segs(s['segments']['goals'])}</table>
<h2>Training level</h2><table><tr><th>Level</th><th>Users</th></tr>{segs(s['segments']['levels'])}</table></div>
</div>
<h2>Week by week</h2>
<div class="wrap-table"><table><tr><th>Week starting</th><th>New users</th><th>Total users</th><th>Active users</th><th>Sets logged</th></tr>{weekly}</table></div>
<footer>"Active" means the user opened the app while signed in{(' (tracked since ' + u['visit_tracking_since'] + ')') if u.get('visit_tracking_since') else ''} or created an entry — a logged set, meal, recovery check-in or a question to the AI coach — in that period. Aggregated data only, no personal information.</footer>
</main></body></html>"""


# ===============================
# БЭКАП: все таблицы -> CSV (+ stats.json и report.html)
# ===============================
def table_csv(conn, table):
    """CSV-текст таблицы и число строк. Пароли и токены сессий не выгружаются."""
    try:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None, 0
    skip = SKIP_COLUMNS.get(table, set())
    cols = [c for c in (rows[0].keys() if rows else []) if c not in skip]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return buf.getvalue(), len(rows)


def build_backup(conn):
    """{имя_файла: bytes} — готово к записи на диск или в zip."""
    files, counts = {}, {}
    for t in BACKUP_TABLES:
        text, n = table_csv(conn, t)
        if text is not None:
            files[f"{t}.csv"] = ("\ufeff" + text).encode("utf-8")   # BOM: Excel откроет кириллицу
            counts[t] = n
    stats = compute_stats(conn)
    stats["row_counts"] = counts
    files["stats.json"] = json.dumps(stats, ensure_ascii=False, indent=2).encode("utf-8")
    files["report.html"] = render_report_html(stats).encode("utf-8")
    return files, stats
