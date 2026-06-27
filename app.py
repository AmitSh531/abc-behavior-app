import os
import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, datetime
import json
import math
import plotly.graph_objects as go

st.set_page_config(
    page_title="ניתוח תצפיות ABC",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .main .block-container { direction: rtl; max-width: 1100px; padding-top: 1.5rem; }
    h1,h2,h3,h4 { text-align: right; }
    p, li, label { direction: rtl; }
    .stTextInput input, .stTextArea textarea { direction: rtl; text-align: right; }
    .stSelectbox > div { direction: rtl; }
    .stAlert > div { direction: rtl; text-align: right; }
    #MainMenu, footer { visibility: hidden; }
    div[data-testid="metric-container"] { direction: rtl; text-align: right; }
    .stRadio > div { direction: rtl; }
    .stCheckbox > label { direction: rtl; }
    /* dataframe RTL */
    [data-testid="stDataFrame"] { direction: rtl; }
    [data-testid="stDataFrame"] table { direction: rtl; }
    [data-testid="stDataFrame"] th,
    [data-testid="stDataFrame"] td { text-align: right !important; }
    /* sidebar RTL */
    section[data-testid="stSidebar"] { direction: rtl; }
    section[data-testid="stSidebar"] * { text-align: right; }
</style>
""", unsafe_allow_html=True)

DB_PATH = "abc_observations.db"

# ─── DATABASE ────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS codes (
        code TEXT PRIMARY KEY,
        description TEXT NOT NULL,
        category TEXT NOT NULL CHECK(category IN ('A','B','C/A')),
        behavior_type TEXT CHECK(behavior_type IN ('appropriate','inappropriate') OR behavior_type IS NULL)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS children (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        dob TEXT,
        framework_name TEXT,
        target_behavior TEXT,
        goal_behavior TEXT,
        notes TEXT
    )""")
    existing_ch = {r[1] for r in c.execute("PRAGMA table_info(children)").fetchall()}
    for col, typ in [("framework_name","TEXT"),("target_behavior","TEXT"),
                     ("goal_behavior","TEXT"),("notes","TEXT")]:
        if col not in existing_ch:
            c.execute(f"ALTER TABLE children ADD COLUMN {col} {typ}")

    c.execute("""CREATE TABLE IF NOT EXISTS observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        child_id INTEGER NOT NULL REFERENCES children(id) ON DELETE CASCADE,
        obs_number TEXT,
        obs_date TEXT NOT NULL,
        start_time TEXT,
        end_time TEXT,
        duration_min INTEGER,
        location TEXT,
        subject TEXT,
        teacher_name TEXT,
        has_assistant INTEGER DEFAULT 0,
        obs_notes TEXT
    )""")
    existing_ob = {r[1] for r in c.execute("PRAGMA table_info(observations)").fetchall()}
    for col, typ in [("subject","TEXT"),("teacher_name","TEXT"),
                     ("has_assistant","INTEGER DEFAULT 0"),("obs_notes","TEXT")]:
        if col not in existing_ob:
            c.execute(f"ALTER TABLE observations ADD COLUMN {col} {typ}")

    c.execute("""CREATE TABLE IF NOT EXISTS episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        observation_id INTEGER NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
        episode_order INTEGER NOT NULL,
        antecedent_code TEXT,
        behavior_code TEXT,
        consequence_code TEXT,
        episode_time TEXT,
        notes TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        child_id INTEGER NOT NULL REFERENCES children(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        title TEXT,
        comparison_time INTEGER,
        obs_ids TEXT,
        result_json TEXT
    )""")

    defaults = [
        ("דר","דרישה","A",None),
        ("משש","מורה שואלת שאלה","A",None),
        ("משק","מורה שואלת שאלות קלואוז","A",None),
        ("מס","מורה מסבירה","A",None),
        ("מנ","מורה נותנת מטלה","A",None),
        ("זמ","זמן מטלה","A",None),
        ("חמצ","חבר מציק","A",None),
        ("מש","זמן משחק","A",None),
        ("המ","המתנה","A",None),
        ("חצ","חבר בצרה","A",None),
        ("נז","נזיפה","C/A",None),
        ("תש","תשומת לב","C/A",None),
        ("תשח","תשומת לב חבר","C/A",None),
        ("הת","התעלמות","C/A",None),
        ("דלר","דיבור ללא רשות","B","inappropriate"),
        ("דבר","דיבור ברשות","B","appropriate"),
        ("מבצ","מבצע מטלה","B","appropriate"),
        ("מצב","מצביע","B","appropriate"),
        ("שש","שואל שאלה","B","appropriate"),
        ("עס","עסוק בחפץ","B","inappropriate"),
        ("מדח","מדבר עם חבר","B","inappropriate"),
        ("עע","עזיבת עמדה","B","inappropriate"),
        ("ילנ","ישיבה לא נאותה","B","inappropriate"),
        ("רכ","רץ אחרי כדור","B","appropriate"),
        ("מד","משתטח על הדשא","B","inappropriate"),
        ("עח","עזרה לחבר","B","appropriate"),
        ("התג","התגרות","B","inappropriate"),
    ]
    for row in defaults:
        c.execute("INSERT OR IGNORE INTO codes VALUES (?,?,?,?)", row)

    conn.commit()
    conn.close()

init_db()

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def query(sql, params=()):
    conn = get_conn()
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df

def execute(sql, params=()):
    conn = get_conn()
    conn.execute(sql, params)
    conn.commit()
    conn.close()

def executemany(sql, rows):
    conn = get_conn()
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()

def get_lastid(sql, params=()):
    conn = get_conn()
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()
    lid = c.lastrowid
    conn.close()
    return lid

def calc_duration(s, e):
    try:
        m = int((datetime.strptime(e, "%H:%M") - datetime.strptime(s, "%H:%M")).seconds / 60)
        return m if m > 0 else None
    except Exception:
        return None

def round_half_up(x):
    return math.floor(x + 0.5)

def build_code_opts(codes_df, categories):
    opts = [""]
    for _, r in codes_df[codes_df["category"].isin(categories)].sort_values("code").iterrows():
        icon = {"appropriate": "🟢 ", "inappropriate": "🔴 "}.get(r["behavior_type"], "")
        opts.append(f"{icon}{r['code']} — {r['description']}")
    return opts

def code_to_label(code, codes_df):
    if not code:
        return ""
    r = codes_df[codes_df["code"] == code]
    if r.empty:
        return code
    icon = {"appropriate": "🟢 ", "inappropriate": "🔴 "}.get(r.iloc[0]["behavior_type"], "")
    return f"{icon}{code} — {r.iloc[0]['description']}"

def extract_code(val):
    if not val or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if not s:
        return None
    for prefix in ["🟢 ", "🔴 "]:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.split(" — ")[0].strip() if " — " in s else (s or None)

def nav(page, **kw):
    st.session_state.page = page
    for k, v in kw.items():
        st.session_state[k] = v

# ─── SESSION STATE INIT ───────────────────────────────────────────────────────

_defaults = {
    "page": "home",
    "child_id": None,
    "obs_id": None,
    "new_obs_meta": {},
    "analysis_obs_ids": [],
    "analysis_comparison_time": 30,
    "sort_field": "obs_date",
    "sort_dir": "DESC",
    "obs_sort_mode": False,
    "analysis_mode": False,
    "success_msg": None,
    "editing_child_id": None,
    "pending_delete_child_id": None,
    "edit_obs_loaded_id": None,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

_EMPTY_ROW = {"notes": "", "time": "", "C": "", "B": "", "A": ""}
if "editor_data" not in st.session_state:
    st.session_state.editor_data = pd.DataFrame([_EMPTY_ROW.copy()])
if "edit_obs_data" not in st.session_state:
    st.session_state.edit_obs_data = pd.DataFrame([_EMPTY_ROW.copy()])

def flash():
    """Show and clear a queued success message."""
    if st.session_state.success_msg:
        st.success(st.session_state.success_msg)
        st.session_state.success_msg = None

def rtl_df(df):
    """Reverse column order so tables read right-to-left."""
    return df[df.columns[::-1]]

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📋 ניתוח ABC")
    st.markdown("---")
    if st.button("🏠  דף הבית", use_container_width=True):
        st.session_state.obs_sort_mode = False
        st.session_state.analysis_mode = False
        nav("home"); st.rerun()
    st.markdown("---")
    if st.button("🚪  יציאה מהאפליקציה", use_container_width=True, type="secondary"):
        os._exit(0)

# ═════════════════════════════════════════════════════════════════════════════
# HOME
# ═════════════════════════════════════════════════════════════════════════════
if st.session_state.page == "home":
    st.markdown("""
    <div style="text-align:center;padding:24px 0 16px">
      <span style="font-size:52px">📋</span>
      <h1 style="color:#1565C0;margin:8px 0 4px;text-align:center">מנתחת התנהגות ABC</h1>
      <p style="color:#888;font-size:15px;text-align:center">כלי לתיעוד וניתוח תצפיות התנהגות</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown("#### 👦 בחרי ילד/ה")
        st.caption("צפייה ברשימת הילדים, הוספת תצפיות וניתוח")
        if st.button("כניסה לרשימת הילדים ←", use_container_width=True,
                     type="primary", key="btn_ch"):
            nav("children"); st.rerun()

    with col2:
        st.markdown("#### 📖 מקרא קודים")
        st.caption("צפייה, עריכה והוספה של קודי תצפית")
        if st.button("כניסה למקרא הקודים ←", use_container_width=True, key="btn_cd"):
            nav("codes"); st.rerun()

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    c1.metric("ילדים במאגר",
              int(query("SELECT COUNT(*) as n FROM children").iloc[0]["n"]))
    c2.metric("תצפיות שמורות",
              int(query("SELECT COUNT(*) as n FROM observations").iloc[0]["n"]))
    c3.metric("קודים במקרא",
              int(query("SELECT COUNT(*) as n FROM codes").iloc[0]["n"]))

# ═════════════════════════════════════════════════════════════════════════════
# CODES
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "codes":
    flash()
    hc, hb = st.columns([4, 1])
    hc.title("📖 מקרא קודים")
    with hb:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← דף הבית"):
            nav("home"); st.rerun()

    codes_df = query("SELECT * FROM codes ORDER BY category, code")
    tab_view, tab_add = st.tabs(["📋 קודים קיימים", "➕ הוספת קוד חדש"])

    with tab_view:
        cat_labels = {
            "A":   "A — נסיבות (Antecedent)",
            "B":   "B — התנהגות (Behavior)",
            "C/A": "C/A — נסיבות / תוצאה",
        }
        for cat, label in cat_labels.items():
            sub = codes_df[codes_df["category"] == cat].copy()
            if sub.empty:
                continue
            st.subheader(label)
            rows = []
            for _, r in sub.iterrows():
                row = {"קוד": r["code"], "פירוש": r["description"], "עמודה": cat}
                if cat == "B":
                    row["נאות/לא נאות"] = (
                        "🟢 נאות" if r["behavior_type"] == "appropriate" else "🔴 לא נאות"
                    )
                else:
                    row["נאות/לא נאות"] = "—"
                rows.append(row)
            st.dataframe(rtl_df(pd.DataFrame(rows)), use_container_width=True, hide_index=True)

            with st.expander(f"✏️ עריכה / מחיקה — {cat}"):
                code_list = list(sub["code"])

                edit_code = st.selectbox("בחרי קוד לעריכה:", ["—"] + code_list,
                                         key=f"edit_sel_{cat}")
                if edit_code != "—":
                    row = sub[sub["code"] == edit_code].iloc[0]
                    with st.form(f"edit_form_{cat}_{edit_code}"):
                        nd = st.text_input("פירוש", value=row["description"])
                        nc = st.selectbox("עמודה", ["A", "B", "C/A"],
                                          index=["A", "B", "C/A"].index(row["category"]))
                        nb = None
                        if nc == "B":
                            bi = 0 if row["behavior_type"] == "inappropriate" else 1
                            nb = "inappropriate" if st.selectbox(
                                "סוג", ["🔴 לא נאות", "🟢 נאות"], index=bi
                            ).startswith("🔴") else "appropriate"
                        if st.form_submit_button("💾 שמור"):
                            execute("UPDATE codes SET description=?,category=?,behavior_type=? WHERE code=?",
                                    (nd, nc, nb, edit_code))
                            st.session_state.success_msg = f"✅ הקוד '{edit_code}' עודכן בהצלחה!"
                            nav("codes"); st.rerun()

                del_code = st.selectbox("בחרי קוד למחיקה:", ["—"] + code_list,
                                        key=f"del_sel_{cat}")
                if del_code != "—":
                    if st.button(f"🗑️ מחיקת '{del_code}'", key=f"del_btn_{cat}"):
                        execute("DELETE FROM codes WHERE code=?", (del_code,))
                        st.session_state.success_msg = f"✅ הקוד '{del_code}' נמחק בהצלחה!"
                        nav("codes"); st.rerun()

            st.markdown("---")

    with tab_add:
        st.subheader("הוספת קוד חדש")
        with st.form("add_code"):
            c1, c2 = st.columns(2)
            cv = c1.text_input("קוד (ייחודי) *")
            dv = c2.text_input("פירוש *")
            cat_map = {"A — נסיבות": "A", "B — התנהגות": "B", "C/A — נסיבות / תוצאה": "C/A"}
            cat_ch = st.selectbox("עמודה בתצפית", list(cat_map.keys()))
            cat_v = cat_map[cat_ch]
            btype_v = None
            if cat_v == "B":
                btype_v = "inappropriate" if st.selectbox(
                    "סוג התנהגות", ["🔴 לא נאות", "🟢 נאות"]
                ).startswith("🔴") else "appropriate"
            if st.form_submit_button("➕ הוספה", type="primary"):
                cv = cv.strip()
                if not cv or not dv.strip():
                    st.error("נא למלא קוד ופירוש")
                else:
                    try:
                        execute("INSERT INTO codes VALUES (?,?,?,?)",
                                (cv, dv.strip(), cat_v, btype_v))
                        st.session_state.success_msg = f"✅ הקוד '{cv}' נוסף בהצלחה!"
                        nav("codes"); st.rerun()
                    except Exception:
                        st.error("קוד זה כבר קיים במקרא")

# ═════════════════════════════════════════════════════════════════════════════
# CHILDREN LIST
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "children":
    flash()
    hc, hb = st.columns([4, 1])
    hc.title("👦 רשימת ילדים")
    with hb:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← דף הבית"):
            nav("home"); st.rerun()

    children = query("SELECT * FROM children ORDER BY name")
    col_list, col_add = st.columns([3, 2])

    with col_add:
        st.markdown("### ➕ הוספת ילד/ה חדש/ה")
        with st.form("add_child"):
            name = st.text_input("שם מלא *")
            dob = st.date_input("תאריך לידה", value=None)
            fw = st.text_input("שם מסגרת")
            tb = st.text_area("התנהגות יעד", height=70)
            gb = st.text_area("התנהגות מטרה", height=70)
            nt = st.text_area("הערות", height=55)
            if st.form_submit_button("💾 הוספה", type="primary"):
                if not name.strip():
                    st.error("נא להזין שם")
                else:
                    get_lastid(
                        "INSERT INTO children (name,dob,framework_name,target_behavior,goal_behavior,notes)"
                        " VALUES (?,?,?,?,?,?)",
                        (name.strip(), str(dob) if dob else None,
                         fw.strip() or None, tb.strip() or None,
                         gb.strip() or None, nt.strip() or None)
                    )
                    st.session_state.success_msg = f"✅ {name} נוסף/ה בהצלחה!"
                    nav("home"); st.rerun()

    with col_list:
        if children.empty:
            st.info("טרם נוספו ילדים. מלאי את הטופס.")
        else:
            st.markdown(f"**{len(children)} ילדים/ות במאגר**")
            for _, ch in children.iterrows():
                cid = int(ch["id"])
                n_obs = int(query("SELECT COUNT(*) as n FROM observations WHERE child_id=?",
                                  (cid,)).iloc[0]["n"])
                editing = (st.session_state.editing_child_id == cid)
                pending_del = (st.session_state.pending_delete_child_id == cid)

                c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
                with c1:
                    parts = []
                    if ch.get("dob"):
                        parts.append(f"ת.לידה: {ch['dob']}")
                    if ch.get("framework_name"):
                        parts.append(f"מסגרת: {ch['framework_name']}")
                    parts.append(f"{n_obs} תצפיות")
                    st.markdown(f"**👤 {ch['name']}**")
                    st.caption(" | ".join(parts))
                with c2:
                    if st.button("📋 פתחי", key=f"open_{cid}",
                                 type="primary", use_container_width=True):
                        nav("child_obs", child_id=cid); st.rerun()
                with c3:
                    if st.button("✏️ ערוך", key=f"edit_{cid}", use_container_width=True):
                        st.session_state.editing_child_id = None if editing else cid
                        st.session_state.pending_delete_child_id = None
                        st.rerun()
                with c4:
                    if not pending_del:
                        if st.button("🗑️ מחק", key=f"del_{cid}", use_container_width=True):
                            st.session_state.pending_delete_child_id = cid
                            st.session_state.editing_child_id = None
                            st.rerun()
                    else:
                        st.warning("בטוח/ה?")
                        if st.button("כן, מחק", key=f"conf_del_{cid}",
                                     type="primary", use_container_width=True):
                            execute("DELETE FROM children WHERE id=?", (cid,))
                            st.session_state.pending_delete_child_id = None
                            st.session_state.success_msg = f"✅ {ch['name']} נמחק/ה (כולל כל התצפיות)."
                            nav("children"); st.rerun()

                if editing:
                    with st.form(f"edit_ch_{cid}"):
                        st.markdown("**✏️ עריכת פרטי ילד/ה**")
                        en = st.text_input("שם מלא *", value=ch["name"])
                        ed = st.date_input("תאריך לידה",
                                           value=date.fromisoformat(ch["dob"]) if ch.get("dob") else None)
                        ef = st.text_input("שם מסגרת", value=ch.get("framework_name") or "")
                        et = st.text_area("התנהגות יעד", value=ch.get("target_behavior") or "", height=60)
                        eg = st.text_area("התנהגות מטרה", value=ch.get("goal_behavior") or "", height=60)
                        eno = st.text_area("הערות", value=ch.get("notes") or "", height=50)
                        cs, cc = st.columns(2)
                        saved = cs.form_submit_button("💾 שמור", type="primary")
                        cancelled = cc.form_submit_button("❌ ביטול")
                        if saved:
                            if not en.strip():
                                st.error("נא להזין שם")
                            else:
                                execute(
                                    "UPDATE children SET name=?,dob=?,framework_name=?,"
                                    "target_behavior=?,goal_behavior=?,notes=? WHERE id=?",
                                    (en.strip(), str(ed) if ed else None,
                                     ef.strip() or None, et.strip() or None,
                                     eg.strip() or None, eno.strip() or None, cid)
                                )
                                st.session_state.editing_child_id = None
                                st.session_state.success_msg = f"✅ {en.strip()} עודכן/ה בהצלחה!"
                                nav("children"); st.rerun()
                        if cancelled:
                            st.session_state.editing_child_id = None
                            st.rerun()

                st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
# CHILD OBSERVATIONS
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "child_obs":
    flash()
    child_id = st.session_state.child_id
    child_df = query("SELECT * FROM children WHERE id=?", (child_id,))
    if child_df.empty:
        nav("children"); st.rerun()
    child = child_df.iloc[0]

    hc, hb = st.columns([4, 1])
    hc.title(f"📋 {child['name']}")
    with hb:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← רשימת ילדים"):
            st.session_state.obs_sort_mode = False
            st.session_state.analysis_mode = False
            nav("children"); st.rerun()

    with st.expander("👤 פרטי הילד/ה"):
        c1, c2 = st.columns(2)
        c1.write(f"**שם מלא:** {child['name']}")
        if child.get("dob"):
            c1.write(f"**תאריך לידה:** {child['dob']}")
        if child.get("framework_name"):
            c1.write(f"**מסגרת:** {child['framework_name']}")
        if child.get("target_behavior"):
            c2.write(f"**התנהגות יעד:** {child['target_behavior']}")
        if child.get("goal_behavior"):
            c2.write(f"**התנהגות מטרה:** {child['goal_behavior']}")
        if child.get("notes"):
            st.write(f"**הערות:** {child['notes']}")

    st.markdown("---")

    sort_mode = st.session_state.obs_sort_mode
    analysis_mode = st.session_state.analysis_mode

    btn1, btn2, btn3 = st.columns(3)
    with btn1:
        if st.button("🔀 סדרי תצפיות", use_container_width=True,
                     type="primary" if sort_mode else "secondary"):
            st.session_state.obs_sort_mode = not sort_mode
            st.session_state.analysis_mode = False
            st.rerun()
    with btn2:
        if st.button("➕ הוספת תצפית", use_container_width=True):
            st.session_state.episodes = [{"A": "", "B": "", "C": "", "time": "", "notes": ""}]
            st.session_state.new_obs_meta = {}
            nav("new_obs_meta", child_id=child_id); st.rerun()
    with btn3:
        if st.button("📊 נתחי תצפיות", use_container_width=True,
                     type="primary" if analysis_mode else "secondary"):
            st.session_state.analysis_mode = not analysis_mode
            st.session_state.obs_sort_mode = False
            st.session_state.analysis_obs_ids = []
            st.rerun()

    if sort_mode:
        st.markdown("---")
        sort_opts = {
            "תאריך": "obs_date",
            "מספר תצפית": "obs_number",
            "שיעור": "subject",
            "מיקום": "location",
            "משך (דקות)": "duration_min",
            "שם מורה": "teacher_name",
        }
        sc1, sc2 = st.columns(2)
        sl = sc1.selectbox("סדרי לפי:", list(sort_opts.keys()))
        sd = sc2.selectbox("סדר:", ["יורד (חדש→ישן)", "עולה (ישן→חדש)"])
        st.session_state.sort_field = sort_opts[sl]
        st.session_state.sort_dir = "DESC" if "יורד" in sd else "ASC"

    if analysis_mode:
        st.markdown("---")
        st.info("✅ סמני תצפיות לניתוח ואז לחצי על 'הפקת ניתוח'")

    sf = st.session_state.sort_field
    sd_val = st.session_state.sort_dir

    obs_all = query(f"""
        SELECT o.*, COUNT(e.id) as ep_count
        FROM observations o
        LEFT JOIN episodes e ON e.observation_id = o.id
        WHERE o.child_id = ?
        GROUP BY o.id
        ORDER BY o.{sf} {sd_val}
    """, (child_id,))

    st.markdown("---")

    if obs_all.empty:
        st.info("טרם נשמרו תצפיות. לחצי על 'הוספת תצפית'.")
    else:
        sel_ids = st.session_state.analysis_obs_ids

        for _, obs in obs_all.iterrows():
            oid = int(obs["id"])
            is_sel = oid in sel_ids

            c_card, c_btn = st.columns([5, 1])
            with c_card:
                check = "✅" if (analysis_mode and is_sel) else ("⬜" if analysis_mode else "📋")
                num = obs.get("obs_number") or f"#{oid}"
                dt = obs.get("obs_date", "")
                subj = obs.get("subject", "") or ""
                title_line = f"{check} **תצפית {num}** | 📅 {dt}" + (f" | 📚 {subj}" if subj else "")
                st.markdown(title_line)

                meta = []
                st_t = obs.get("start_time") or ""
                en_t = obs.get("end_time") or ""
                if st_t and en_t:
                    meta.append(f"⏰ {st_t}–{en_t}")
                if obs.get("duration_min"):
                    meta.append(f"⏱ {int(obs['duration_min'])} דקות")
                if obs.get("location"):
                    meta.append(f"📍 {obs['location']}")
                if obs.get("teacher_name"):
                    meta.append(f"👩‍🏫 {obs['teacher_name']}")
                if obs.get("has_assistant"):
                    meta.append("🤝 יש סייעת")
                meta.append(f"📊 {int(obs['ep_count'])} אפיזודות")
                st.caption(" | ".join(meta))

            with c_btn:
                if analysis_mode:
                    if is_sel:
                        if st.button("הסר", key=f"desel_{oid}", use_container_width=True):
                            sel_ids.remove(oid)
                            st.session_state.analysis_obs_ids = sel_ids
                            st.rerun()
                    else:
                        if st.button("בחרי", key=f"sel_{oid}", use_container_width=True,
                                     type="primary"):
                            sel_ids.append(oid)
                            st.session_state.analysis_obs_ids = sel_ids
                            st.rerun()
                else:
                    if st.button("פתחי", key=f"view_{oid}", use_container_width=True):
                        nav("view_obs", obs_id=oid); st.rerun()
            st.markdown("---")

        if analysis_mode:
            if sel_ids:
                st.success(f"נבחרו {len(sel_ids)} תצפיות")
                if st.button("📊 המשיכי לניתוח ←", type="primary",
                             use_container_width=True):
                    nav("analysis_select", child_id=child_id); st.rerun()
            else:
                st.warning("נא לבחור לפחות תצפית אחת")

    # Saved analyses tab
    saved = query("SELECT * FROM analyses WHERE child_id=? ORDER BY created_at DESC",
                  (child_id,))
    if not saved.empty:
        with st.expander(f"💾 ניתוחים שמורים ({len(saved)})"):
            for _, an in saved.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(f"**{an['title'] or 'ניתוח'}** — {an['created_at'][:10]} | "
                         f"זמן השוואה: {an['comparison_time']} דקות")
                with c2:
                    if st.button("🗑️", key=f"del_an_{an['id']}"):
                        execute("DELETE FROM analyses WHERE id=?", (an["id"],))
                        st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# VIEW OBSERVATION
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "view_obs":
    flash()
    obs_id = st.session_state.obs_id
    obs_df = query(
        "SELECT o.*, c.name as child_name FROM observations o "
        "JOIN children c ON o.child_id=c.id WHERE o.id=?", (obs_id,)
    )
    if obs_df.empty:
        nav("children"); st.rerun()
    obs = obs_df.iloc[0]

    hc, hb, he = st.columns([3, 1, 1])
    hc.title(f"📋 תצפית — {obs['child_name']}")
    with he:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✏️ ערוך תצפית", use_container_width=True):
            st.session_state.edit_obs_loaded_id = None
            nav("edit_obs", obs_id=obs_id); st.rerun()
    with hb:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← תצפיות"):
            nav("child_obs", child_id=int(obs["child_id"])); st.rerun()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("תאריך", obs["obs_date"])
    m2.metric("שעות", f"{obs.get('start_time','?')} – {obs.get('end_time','?')}")
    m3.metric("משך", f"{int(obs['duration_min'])} דקות" if obs.get("duration_min") else "—")
    m4.metric("מספר תצפית", obs.get("obs_number") or "—")

    c1, c2, c3 = st.columns(3)
    c1.write(f"**מיקום:** {obs.get('location') or '—'}")
    c2.write(f"**שיעור:** {obs.get('subject') or '—'}")
    c3.write(f"**מורה:** {obs.get('teacher_name') or '—'}")
    st.write(f"**סייעת:** {'כן' if obs.get('has_assistant') else 'לא'}")
    if obs.get("obs_notes"):
        st.write(f"**הערות:** {obs['obs_notes']}")

    st.markdown("---")
    codes_df = query("SELECT * FROM codes")
    eps = query("SELECT * FROM episodes WHERE observation_id=? ORDER BY episode_order", (obs_id,))

    if eps.empty:
        st.info("אין אפיזודות בתצפית זו.")
    else:
        st.subheader(f"אפיזודות ({len(eps)})")

        disp = eps.copy()
        disp["antecedent_code"] = disp["antecedent_code"].fillna("—")
        disp["behavior_code"] = disp["behavior_code"].fillna("—")
        disp["consequence_code"] = disp["consequence_code"].fillna("—")
        disp = disp[["episode_order", "episode_time", "antecedent_code",
                      "behavior_code", "consequence_code", "notes"]]
        disp.columns = ["#", "שעה", "נסיבות (A)", "התנהגות (B)", "תוצאה (C)", "הערות"]
        st.dataframe(rtl_df(disp), use_container_width=True, hide_index=True)

        bm = eps[eps["behavior_code"].notna()].merge(
            codes_df[["code", "behavior_type"]], left_on="behavior_code",
            right_on="code", how="left"
        )
        inapp = int((bm["behavior_type"] == "inappropriate").sum())
        app_c = int((bm["behavior_type"] == "appropriate").sum())
        st.markdown("---")
        mc1, mc2 = st.columns(2)
        mc1.metric("🔴 התנהגויות לא נאות", inapp)
        mc2.metric("🟢 התנהגויות נאות", app_c)

    st.markdown("---")
    if st.button("🗑️ מחיקת תצפית זו", type="secondary"):
        execute("DELETE FROM observations WHERE id=?", (obs_id,))
        nav("child_obs", child_id=int(obs["child_id"])); st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# EDIT OBSERVATION
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "edit_obs":
    obs_id = st.session_state.obs_id
    obs_df = query(
        "SELECT o.*, c.name as child_name FROM observations o "
        "JOIN children c ON o.child_id=c.id WHERE o.id=?", (obs_id,)
    )
    if obs_df.empty:
        nav("children"); st.rerun()
    obs = obs_df.iloc[0]
    child_id = int(obs["child_id"])

    hc, hb = st.columns([4, 1])
    hc.title(f"✏️ עריכת תצפית — {obs['child_name']}")
    with hb:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← ביטול"):
            nav("view_obs", obs_id=obs_id); st.rerun()

    codes_df = query("SELECT * FROM codes ORDER BY category, code")

    if st.session_state.edit_obs_loaded_id != obs_id:
        eps_db = query(
            "SELECT * FROM episodes WHERE observation_id=? ORDER BY episode_order", (obs_id,)
        )
        if eps_db.empty:
            st.session_state.edit_obs_data = pd.DataFrame([_EMPTY_ROW.copy()])
        else:
            rows = []
            for _, ep in eps_db.iterrows():
                rows.append({
                    "notes": ep["notes"] or "",
                    "time": ep["episode_time"] or "",
                    "C": code_to_label(ep["consequence_code"], codes_df),
                    "B": code_to_label(ep["behavior_code"], codes_df),
                    "A": code_to_label(ep["antecedent_code"], codes_df),
                })
            st.session_state.edit_obs_data = pd.DataFrame(rows)
        st.session_state.edit_obs_loaded_id = obs_id

    st.subheader("פרטי התצפית")
    with st.form("edit_obs_meta"):
        c1, c2 = st.columns(2)
        obs_number = c1.text_input("מספר תצפית", value=obs.get("obs_number") or "")
        obs_date_v = c2.date_input(
            "תאריך",
            value=date.fromisoformat(obs["obs_date"]) if obs.get("obs_date") else date.today()
        )
        c3, c4 = st.columns(2)
        st_time = c3.text_input("שעת התחלה (HH:MM)", value=obs.get("start_time") or "")
        en_time = c4.text_input("שעת סיום (HH:MM)", value=obs.get("end_time") or "")
        c5, c6 = st.columns(2)
        location = c5.text_input("מיקום", value=obs.get("location") or "")
        subject = c6.text_input("שיעור", value=obs.get("subject") or "")
        c7, c8 = st.columns(2)
        teacher = c7.text_input("שם המורה", value=obs.get("teacher_name") or "")
        asst_idx = 1 if obs.get("has_assistant") else 0
        has_asst = c8.selectbox("יש סייעת?", ["לא", "כן"], index=asst_idx)
        obs_notes = st.text_area("הערות לתצפית", value=obs.get("obs_notes") or "", height=60)
        if st.form_submit_button("שמור פרטים ועבור לאפיזודות ←", type="primary"):
            dur = calc_duration(st_time, en_time) if st_time and en_time else None
            execute(
                "UPDATE observations SET obs_number=?,obs_date=?,start_time=?,end_time=?,"
                "duration_min=?,location=?,subject=?,teacher_name=?,has_assistant=?,obs_notes=? "
                "WHERE id=?",
                (obs_number.strip() or None, str(obs_date_v),
                 st_time.strip() or None, en_time.strip() or None, dur,
                 location.strip() or None, subject.strip() or None,
                 teacher.strip() or None, 1 if has_asst == "כן" else 0,
                 obs_notes.strip() or None, obs_id)
            )
            st.rerun()

    st.markdown("---")
    st.subheader("אפיזודות")
    st.caption("לחצי Tab לעבור בין תאים. לחצי ➕ בתחתית הטבלה להוספת שורה.")

    a_opts = build_code_opts(codes_df, ["A", "C/A"])
    b_opts = build_code_opts(codes_df, ["B"])
    c_opts = build_code_opts(codes_df, ["C/A"])

    edited = st.data_editor(
        st.session_state.edit_obs_data,
        column_config={
            "A": st.column_config.SelectboxColumn("A — נסיבות", options=a_opts, required=False),
            "B": st.column_config.SelectboxColumn("B — התנהגות", options=b_opts, required=False),
            "C": st.column_config.SelectboxColumn("C — תוצאה", options=c_opts, required=False),
            "time": st.column_config.TextColumn("שעה", width="small"),
            "notes": st.column_config.TextColumn("הערות"),
        },
        num_rows="dynamic",
        use_container_width=True,
        key="ep_editor_edit",
        hide_index=False,
    )
    st.session_state.edit_obs_data = edited

    st.markdown("---")
    if st.button("💾 שמירת שינויים", type="primary", use_container_width=True):
        rows = edited.to_dict("records")
        valid = [r for r in rows
                 if extract_code(r.get("A")) or extract_code(r.get("B")) or extract_code(r.get("C"))]
        if not valid:
            st.error("נא להזין לפחות שורה אחת עם קוד")
        else:
            execute("DELETE FROM episodes WHERE observation_id=?", (obs_id,))
            executemany(
                "INSERT INTO episodes "
                "(observation_id,episode_order,antecedent_code,behavior_code,"
                "consequence_code,episode_time,notes) VALUES (?,?,?,?,?,?,?)",
                [(obs_id, idx + 1,
                  extract_code(r.get("A")), extract_code(r.get("B")),
                  extract_code(r.get("C")),
                  str(r.get("time") or "").strip() or None,
                  str(r.get("notes") or "").strip() or None)
                 for idx, r in enumerate(valid)]
            )
            st.session_state.success_msg = "✅ התצפית עודכנה בהצלחה!"
            st.session_state.edit_obs_loaded_id = None
            nav("view_obs", obs_id=obs_id); st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# NEW OBSERVATION — METADATA
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "new_obs_meta":
    child_id = st.session_state.child_id
    child = query("SELECT * FROM children WHERE id=?", (child_id,)).iloc[0]

    hc, hb = st.columns([4, 1])
    hc.title(f"➕ תצפית חדשה — {child['name']}")
    with hb:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← ביטול"):
            nav("child_obs", child_id=child_id); st.rerun()

    st.subheader("שלב 1 מתוך 2 — פרטי התצפית")

    with st.form("meta_form"):
        c1, c2 = st.columns(2)
        obs_number = c1.text_input("מספר תצפית")
        obs_date = c2.date_input("תאריך", value=date.today())

        c3, c4 = st.columns(2)
        st_time = c3.text_input("שעת התחלה (HH:MM)", placeholder="09:00")
        en_time = c4.text_input("שעת סיום (HH:MM)", placeholder="09:30")

        c5, c6 = st.columns(2)
        location = c5.text_input("מיקום")
        subject = c6.text_input("שיעור (נושא)")

        c7, c8 = st.columns(2)
        teacher = c7.text_input("שם המורה")
        has_asst = c8.selectbox("יש סייעת?", ["לא", "כן"])

        obs_notes = st.text_area("הערות לתצפית", height=60)

        if st.form_submit_button("המשך לרישום אפיזודות ←", type="primary"):
            dur = calc_duration(st_time, en_time) if st_time and en_time else None
            st.session_state.new_obs_meta = {
                "child_id": child_id,
                "obs_number": obs_number.strip() or None,
                "obs_date": str(obs_date),
                "start_time": st_time.strip() or None,
                "end_time": en_time.strip() or None,
                "duration_min": dur,
                "location": location.strip() or None,
                "subject": subject.strip() or None,
                "teacher_name": teacher.strip() or None,
                "has_assistant": 1 if has_asst == "כן" else 0,
                "obs_notes": obs_notes.strip() or None,
            }
            if not st.session_state.episodes:
                st.session_state.episodes = [{"A": "", "B": "", "C": "", "time": "", "notes": ""}]
            nav("new_obs_eps"); st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# NEW OBSERVATION — EPISODES
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "new_obs_eps":
    child_id = st.session_state.child_id
    child = query("SELECT * FROM children WHERE id=?", (child_id,)).iloc[0]
    meta = st.session_state.new_obs_meta

    hc, hb = st.columns([4, 1])
    hc.title(f"➕ רישום אפיזודות — {child['name']}")
    if meta.get("duration_min"):
        hc.caption(f"מס' {meta.get('obs_number','')} | {meta.get('obs_date','')} | "
                   f"{meta['duration_min']} דקות")
    with hb:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← פרטי תצפית"):
            nav("new_obs_meta", child_id=child_id); st.rerun()

    codes_df = query("SELECT * FROM codes ORDER BY category, code")

    a_opts = build_code_opts(codes_df, ["A", "C/A"])
    b_opts = build_code_opts(codes_df, ["B"])
    c_opts = build_code_opts(codes_df, ["C/A"])

    st.subheader("שלב 2 מתוך 2 — טבלת אפיזודות ABC")
    st.caption("💡 לחצי/געי בכל תא לבחירה (לא Enter). לתא הבא: Tab. לשורה חדשה: לחצי ➕ בתחתית הטבלה. עמודות מימין לשמאל: A | B | C | שעה | הערות")

    edited = st.data_editor(
        st.session_state.editor_data,
        column_config={
            "A": st.column_config.SelectboxColumn("A — נסיבות", options=a_opts, required=False),
            "B": st.column_config.SelectboxColumn("B — התנהגות", options=b_opts, required=False),
            "C": st.column_config.SelectboxColumn("C — תוצאה", options=c_opts, required=False),
            "time": st.column_config.TextColumn("שעה", width="small"),
            "notes": st.column_config.TextColumn("הערות"),
        },
        num_rows="dynamic",
        use_container_width=True,
        key="ep_editor_new",
        hide_index=False,
    )
    st.session_state.editor_data = edited

    st.markdown("---")
    if st.button("💾 שמירת תצפית", type="primary", use_container_width=True):
        rows = edited.to_dict("records")
        valid = [r for r in rows
                 if extract_code(r.get("A")) or extract_code(r.get("B")) or extract_code(r.get("C"))]
        if not valid:
            st.error("נא להזין לפחות שורה אחת עם קוד")
        else:
            oid = get_lastid(
                "INSERT INTO observations "
                "(child_id,obs_number,obs_date,start_time,end_time,duration_min,"
                "location,subject,teacher_name,has_assistant,obs_notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (meta["child_id"], meta.get("obs_number"), meta["obs_date"],
                 meta.get("start_time"), meta.get("end_time"), meta.get("duration_min"),
                 meta.get("location"), meta.get("subject"), meta.get("teacher_name"),
                 meta.get("has_assistant", 0), meta.get("obs_notes"))
            )
            executemany(
                "INSERT INTO episodes "
                "(observation_id,episode_order,antecedent_code,behavior_code,"
                "consequence_code,episode_time,notes) VALUES (?,?,?,?,?,?,?)",
                [(oid, idx + 1,
                  extract_code(r.get("A")), extract_code(r.get("B")),
                  extract_code(r.get("C")),
                  str(r.get("time") or "").strip() or None,
                  str(r.get("notes") or "").strip() or None)
                 for idx, r in enumerate(valid)]
            )
            st.session_state.success_msg = "✅ התצפית נשמרה בהצלחה!"
            st.session_state.editor_data = pd.DataFrame([_EMPTY_ROW.copy()])
            nav("child_obs", child_id=child_id); st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# ANALYSIS — SELECT COMPARISON TIME
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "analysis_select":
    child_id = st.session_state.child_id
    child = query("SELECT * FROM children WHERE id=?", (child_id,)).iloc[0]
    sel_ids = st.session_state.analysis_obs_ids

    hc, hb = st.columns([4, 1])
    hc.title(f"📊 ניתוח — {child['name']}")
    with hb:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← תצפיות"):
            nav("child_obs", child_id=child_id); st.rerun()

    if not sel_ids:
        st.warning("לא נבחרו תצפיות."); st.stop()

    st.subheader(f"תצפיות נבחרות ({len(sel_ids)})")
    durations = []
    for oid in sel_ids:
        o = query("SELECT * FROM observations WHERE id=?", (oid,))
        if o.empty:
            continue
        o = o.iloc[0]
        dur = o.get("duration_min")
        subj = o.get("subject") or ""
        num = o.get("obs_number") or f"#{oid}"
        st.write(f"✅ תצפית {num} | {o.get('obs_date','')} | "
                 f"{int(dur) if dur else '?'} דקות{' | ' + subj if subj else ''}")
        if dur:
            durations.append(int(dur))

    st.markdown("---")
    st.subheader("בחרי זמן השוואה (ערך משולש)")
    st.caption("ספירות האפיזודות מכל תצפית יוכפלו ביחס בין זמן ההשוואה לאורך התצפית.")

    if durations:
        opts = [f"{d} דקות" for d in sorted(set(durations))] + ["זמן אחר"]
        chosen = st.radio("זמן השוואה:", opts, horizontal=True)
        if "אחר" in chosen:
            cmp_time = st.number_input("הזיני דקות:", min_value=1,
                                       value=max(durations))
        else:
            cmp_time = int(chosen.replace(" דקות", ""))
    else:
        cmp_time = st.number_input("הזיני דקות:", min_value=1, value=30)

    st.markdown("---")
    if st.button("📊 הפקת ניתוח ←", type="primary", use_container_width=True):
        st.session_state.analysis_comparison_time = cmp_time
        nav("analysis_result", child_id=child_id); st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# ANALYSIS — RESULTS
# ═════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "analysis_result":
    child_id = st.session_state.child_id
    child = query("SELECT * FROM children WHERE id=?", (child_id,)).iloc[0]
    sel_ids = st.session_state.analysis_obs_ids
    cmp_time = st.session_state.analysis_comparison_time

    hc, hb = st.columns([4, 1])
    hc.title(f"📊 תוצאות ניתוח — {child['name']}")
    with hb:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← בחירת זמן"):
            nav("analysis_select", child_id=child_id); st.rerun()

    codes_df = query("SELECT * FROM codes")

    inapp_totals: dict = {}
    app_totals: dict = {}
    obs_dates = []

    for oid in sel_ids:
        o = query("SELECT * FROM observations WHERE id=?", (oid,))
        if o.empty:
            continue
        o = o.iloc[0]
        dur = o.get("duration_min") or 1
        if o.get("obs_date"):
            obs_dates.append(o["obs_date"])
        factor = cmp_time / dur
        eps = query("SELECT * FROM episodes WHERE observation_id=?", (oid,))

        for _, ep in eps.iterrows():
            bc = ep.get("behavior_code")
            if not bc:
                continue
            ci = codes_df[codes_df["code"] == bc]
            if ci.empty:
                continue
            bt = ci.iloc[0]["behavior_type"]
            if bt == "inappropriate":
                inapp_totals[bc] = inapp_totals.get(bc, 0) + factor
            elif bt == "appropriate":
                app_totals[bc] = app_totals.get(bc, 0) + factor

    inapp_final = {c: round_half_up(v) for c, v in inapp_totals.items() if v > 0}
    app_final = {c: round_half_up(v) for c, v in app_totals.items() if v > 0}

    obs_dates_s = sorted(obs_dates)
    date_range = (f"{obs_dates_s[0]} — {obs_dates_s[-1]}"
                  if len(obs_dates_s) > 1 else (obs_dates_s[0] if obs_dates_s else ""))

    # Header
    st.markdown(f"""
**ילד/ה:** {child['name']}  |  **זמן השוואה:** {cmp_time} דקות  |
**מספר תצפיות:** {len(sel_ids)}  |  **טווח תאריכים:** {date_range}
""")
    st.markdown("---")

    def build_df(totals):
        rows = []
        for code, cnt in sorted(totals.items(), key=lambda x: -x[1]):
            ci = codes_df[codes_df["code"] == code]
            desc = ci.iloc[0]["description"] if not ci.empty else ""
            rows.append({"קוד": code, "תיאור": desc, "מספר הופעות": cnt})
        return pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["קוד", "תיאור", "מספר הופעות"])

    df_inapp = build_df(inapp_final)
    df_app = build_df(app_final)

    tc1, tc2 = st.columns(2)
    with tc1:
        st.subheader("🔴 התנהגויות לא נאות")
        if df_inapp.empty:
            st.info("לא נמצאו")
        else:
            st.dataframe(rtl_df(df_inapp), use_container_width=True, hide_index=True)

    with tc2:
        st.subheader("🟢 התנהגויות נאות")
        if df_app.empty:
            st.info("לא נמצאו")
        else:
            st.dataframe(rtl_df(df_app), use_container_width=True, hide_index=True)

    st.markdown("---")

    if not df_inapp.empty:
        st.subheader("📊 גרף התנהגויות לא נאות")
        fig1 = go.Figure(go.Bar(
            x=df_inapp["קוד"], y=df_inapp["מספר הופעות"],
            marker_color="#D85A30",
            text=df_inapp["מספר הופעות"], textposition="auto",
            customdata=df_inapp["תיאור"],
            hovertemplate="<b>%{x}</b> — %{customdata}<br>הופעות: %{y}<extra></extra>"
        ))
        fig1.update_layout(xaxis_title="קוד", yaxis_title="מספר הופעות",
                           plot_bgcolor="white", showlegend=False)
        st.plotly_chart(fig1, use_container_width=True)

    if not df_app.empty:
        st.subheader("📊 גרף התנהגויות נאות")
        fig2 = go.Figure(go.Bar(
            x=df_app["קוד"], y=df_app["מספר הופעות"],
            marker_color="#1D9E75",
            text=df_app["מספר הופעות"], textposition="auto",
            customdata=df_app["תיאור"],
            hovertemplate="<b>%{x}</b> — %{customdata}<br>הופעות: %{y}<extra></extra>"
        ))
        fig2.update_layout(xaxis_title="קוד", yaxis_title="מספר הופעות",
                           plot_bgcolor="white", showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")
    sc1, sc2 = st.columns(2)

    with sc1:
        st.subheader("💾 שמירת הניתוח")
        an_title = st.text_input("שם הניתוח",
                                  value=f"ניתוח {child['name']} — {date_range}")
        if st.button("💾 שמור", type="primary", use_container_width=True):
            get_lastid(
                "INSERT INTO analyses "
                "(child_id,created_at,title,comparison_time,obs_ids,result_json)"
                " VALUES (?,?,?,?,?,?)",
                (child_id, datetime.now().isoformat()[:10], an_title,
                 cmp_time, json.dumps(sel_ids),
                 json.dumps({"inapp": inapp_final, "app": app_final}, ensure_ascii=False))
            )
            st.session_state.success_msg = f"✅ הניתוח '{an_title}' נשמר בהצלחה!"
            nav("child_obs", child_id=child_id); st.rerun()

    with sc2:
        st.subheader("📤 ייצוא HTML")
        ri = "".join(
            f"<tr><td>{r['קוד']}</td><td>{r['תיאור']}</td><td>{r['מספר הופעות']}</td></tr>"
            for _, r in df_inapp.iterrows()
        ) if not df_inapp.empty else "<tr><td colspan='3'>—</td></tr>"
        ra = "".join(
            f"<tr><td>{r['קוד']}</td><td>{r['תיאור']}</td><td>{r['מספר הופעות']}</td></tr>"
            for _, r in df_app.iterrows()
        ) if not df_app.empty else "<tr><td colspan='3'>—</td></tr>"

        html = f"""<!DOCTYPE html><html dir="rtl" lang="he"><head>
<meta charset="UTF-8"><title>ניתוח — {child['name']}</title>
<style>body{{font-family:Arial,sans-serif;direction:rtl;padding:24px}}
h1{{color:#1565C0}}table{{border-collapse:collapse;width:65%;margin:12px 0 24px}}
th{{background:#eef2ff;padding:8px 14px;border:1px solid #ccc}}
td{{padding:8px 14px;border:1px solid #ccc}}</style></head><body>
<h1>📋 ניתוח תצפיות ABC</h1>
<p><b>ילד/ה:</b> {child['name']}</p>
<p><b>זמן השוואה:</b> {cmp_time} דקות | <b>תצפיות:</b> {len(sel_ids)} | <b>תאריכים:</b> {date_range}</p>
<hr>
<h2 style="color:#D85A30">🔴 התנהגויות לא נאות</h2>
<table><tr><th>קוד</th><th>תיאור</th><th>הופעות</th></tr>{ri}</table>
<h2 style="color:#1D9E75">🟢 התנהגויות נאות</h2>
<table><tr><th>קוד</th><th>תיאור</th><th>הופעות</th></tr>{ra}</table>
</body></html>"""

        st.download_button(
            "📥 הורדת דוח HTML",
            data=html.encode("utf-8"),
            file_name=f"analysis_{child['name']}_{date.today()}.html",
            mime="text/html",
            use_container_width=True,
        )
