import streamlit as st
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import io
import time
import instaloader
import xlsxwriter
import re
import os
import hashlib
import sqlite3
import calendar

# ============ CACHING & SESSION MANAGEMENT ============
class ScrapingCache:
    """Simple cache untuk hasil scraping dengan TTL"""
    def __init__(self, ttl_minutes=60):
        self.cache = {}
        self.ttl = timedelta(minutes=ttl_minutes)
    
    def get(self, key):
        """Get cached value jika belum expired"""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key, value):
        """Set cache value dengan timestamp"""
        self.cache[key] = (value, datetime.now())
    
    def clear_expired(self):
        """Remove expired entries"""
        now = datetime.now()
        expired_keys = [k for k, (_, ts) in self.cache.items() if now - ts >= self.ttl]
        for k in expired_keys:
            del self.cache[k]

# Global cache instance (1 hour TTL)
scraping_cache = ScrapingCache(ttl_minutes=60)

# CONFIGURATION 
DB_PATH = os.path.abspath("PLN_Ultimate_Monitoring_V7.db")
DB_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})

def get_db_connection():
    """Get direct SQLite connection with WAL mode for better concurrency"""
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def update_password_direct(user_id, new_password_hash):
    """Update password using direct SQLite connection with verification"""
    conn = None
    try:
        # Update
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password = ? WHERE id = ?", (new_password_hash, user_id))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        
        if affected == 0:
            return False
        
        # Verify in fresh connection
        import time
        time.sleep(0.2)  # small delay to ensure write is flushed
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        return result is not None and result[0] == new_password_hash
        
    except Exception as e:
        try:
            if conn:
                conn.close()
        except:
            pass
        return False

def verify_password_after_update(user_id, password_hash):
    """Verify password matches in fresh connection"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM users WHERE id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None and result[0] == password_hash
    except Exception as e:
        try:
            if conn:
                conn.close()
        except:
            pass
        return False

st.set_page_config(
    page_title="PLN UID Lampung Humas",
    layout="wide",
    page_icon="⚡",
    initial_sidebar_state="collapsed"
)

# ============ AUTHENTICATION & ROLE SYSTEM ============
def init_auth_db():
    """Initialize users and roles table"""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                unit TEXT,
                created_at TEXT
            )
        """))
        # create default admin if not exists
        admin_pass = hashlib.sha256('admin123'.encode()).hexdigest()
        try:
            conn.execute(text("""
                INSERT INTO users (username, password, role, unit, created_at)
                VALUES ('admin', :pass, 'admin', 'ADMIN', :ca)
            """), {"pass": admin_pass, "ca": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        except Exception:
            pass


def login_user(username, password):
    """Verify credentials and return user info dict or None"""
    try:
        hashed = verify_password(password)
        with engine.begin() as conn:
            row = conn.execute(text("SELECT id, username, role, unit FROM users WHERE username=:u AND password=:p"), {"u": username, "p": hashed}).fetchone()
        if row:
            return {"id": row[0], "username": row[1], "role": row[2], "unit": row[3]}
    except Exception:
        return None
    return None


def verify_password(password):
    """Hash password untuk keamanan (SHA256)"""
    return hashlib.sha256(password.encode()).hexdigest()


def register_user(username, password, role='user', unit=''):
    """Register a new user. Returns True on success, False if username exists."""
    hashed = verify_password(password)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (username, password, role, unit, created_at) VALUES (:u, :p, :r, :unit, :ca)"),
                         {"u": username, "p": hashed, "r": role, "unit": unit, "ca": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        return True
    except Exception:
        return False

def show_login_page():
    """Halaman Login Selaras: Header dan Form memiliki lebar yang sama."""
    
    # 1. CSS untuk Penyelarasan Visual
    st.markdown("""
        <style>
            /* Container Utama untuk mengontrol lebar agar header & form sinkron */
            .auth-container {
                max-width: 550px;
                margin: 0 auto;
            }

            /* Header Box - Warna Biru PLN Senada */
            .login-header {
                background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
                padding: 30px;
                border-radius: 20px;
                text-align: center;
                margin-bottom: 25px;
                box-shadow: 0 4px 15px rgba(30, 58, 138, 0.2);
            }
            .login-header h1 {
                color: white !important;
                font-size: 24px !important;
                margin: 0 !important;
                font-weight: 800 !important;
                letter-spacing: 1px;
            }
            .login-header p {
                color: #e0f2fe !important;
                margin-top: 5px !important;
                font-size: 14px !important;
                opacity: 0.9;
            }

            /* Tombol - Warna disamakan dengan Biru Header agar selaras */
            div.stButton > button {
                background-color: #1e3a8a !important; /* Biru PLN Tua */
                color: white !important;
                border: none !important;
                padding: 10px 0px !important;
                font-weight: 700 !important;
                border-radius: 12px !important;
                transition: 0.3s ease;
                height: 50px;
                margin-top: 15px;
            }
            
            div.stButton > button:hover {
                background-color: #0ea5e9 !important; /* Switch ke Biru Muda saat hover */
                box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3) !important;
            }

            /* Input Field styling agar lebih modern */
            .stTextInput input {
                border-radius: 10px !important;
            }

            /* Menghilangkan border default tabs agar lebih clean */
            .stTabs [data-baseweb="tab-highlight"] {
                background-color: #1e3a8a !important;
            }
        </style>
    """, unsafe_allow_html=True)
    _, center_col, _ = st.columns([0.8, 2, 0.8])
    with center_col:
        # Header  lebarnya kan sama dengan form
        st.markdown("""
            <div class="login-header">
                <h1>⚡ PORTAL KOMUNIKASI PLN UID LAMPUNG</h1>
                <p>Platform Manajemen Sosmed & Pengadaan Dokumentasi</p>
            </div>
        """, unsafe_allow_html=True)

        tab1, tab2 = st.tabs(["🔐 LOGIN", "📝 DAFTAR"])

        with tab1:
            st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
            u_log = st.text_input("Username", key="auth_u_log")
            p_log = st.text_input("Password", type="password", key="auth_p_log")
            
            if st.button("MASUK SEKARANG", use_container_width=True, key="btn_login_final"):
                if not u_log or not p_log:
                    st.error("Silakan isi semua bidang!")
                else:
                    user = login_user(u_log, p_log)
                    if user:
                        st.session_state.user = user
                        st.session_state.current_nav = "Dashboard Admin" if user.get('role') == 'admin' else "Dashboard User"
                        st.success("✅ Login Berhasil!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ Username atau password salah")

        with tab2:
            st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
            u_reg = st.text_input("Username Baru", key="auth_u_reg")
            
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                p_reg = st.text_input("Password", type="password", key="auth_p_reg")
            with col_p2:
                pc_reg = st.text_input("Konfirmasi", type="password", key="auth_pc_reg")
            
            unit_reg = st.text_input("Unit Kerja", key="auth_unit_reg", placeholder="Contoh: Humas UID")

            if st.button("DAFTAR SEKARANG", use_container_width=True, key="btn_reg_final"):
                if not all([u_reg, p_reg, pc_reg, unit_reg]):
                    st.error("⚠️ Lengkapi seluruh data!")
                elif len(p_reg) < 6:
                    st.error("⚠️ Password minimal 6 karakter!")
                elif p_reg != pc_reg:
                    st.error("⚠️ Password tidak sesuai!")
                elif register_user(u_reg, p_reg, 'user', unit_reg):
                    st.success("✅ Berhasil! Silakan Login.")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("❌ Username sudah terpakai")

# Initialize databases
init_auth_db()

# Check if user is logged in
if 'user' not in st.session_state:
    show_login_page()
    st.stop()

# Initialize default nav for admin on first login
if 'current_nav' not in st.session_state:
    user_role = st.session_state.user.get('role', 'user')
    if user_role == "admin":
        st.session_state.current_nav = "Dashboard Admin"
    else:
        st.session_state.current_nav = "Dashboard User"

# ============ INITIALIZE SESSION STATE & DATABASE ============
def init_db():
    """Initialize database tables"""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS daftar_akun_unit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama_unit TEXT,
                    username_ig TEXT UNIQUE
                )
            """))
            
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS monitoring_pln (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tanggal TEXT, bulan TEXT, tahun TEXT,
                    judul_pemberitaan TEXT, 
                    link_pemberitaan TEXT UNIQUE,
                    platform TEXT, tipe_konten TEXT, 
                    pic_unit TEXT, 
                    akun TEXT,
                    kategori TEXT,
                    likes INTEGER DEFAULT 0, 
                    comments INTEGER DEFAULT 0,
                    views INTEGER DEFAULT 0,
                    last_updated TEXT
                )
            """))
            # Ensure unique index exists for ON CONFLICT to work reliably
            try:
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_monitoring_link ON monitoring_pln(link_pemberitaan)"))
            except Exception:
                pass

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS pengajuan_dokumentasi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama_pengaju TEXT,
                    user_id INTEGER,
                    nomor_telpon TEXT,
                    unit TEXT,
                    tanggal_acara TEXT,
                    jam_mulai TEXT,
                    jam_selesai TEXT,
                    output_link_drive TEXT,
                    output_type TEXT,
                    biaya REAL DEFAULT 0,
                    deadline_penyelesaian TEXT,
                    status TEXT DEFAULT 'pending',
                    hasil_link_drive TEXT,
                    added_to_calendar INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    notes TEXT
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS dokumentasi_calendar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pengajuan_id INTEGER,
                    tanggal TEXT,
                    nama_kegiatan TEXT,
                    unit TEXT,
                    status TEXT,
                    created_at TEXT
                )
            """))

            # --- Migration: ensure expected columns exist for backwards compatibility ---
            def ensure_columns(table_name, columns):
                # columns: dict of column_name -> column_definition (e.g. "user_id INTEGER")
                existing = [r[1] for r in conn.execute(text(f"PRAGMA table_info('{table_name}')")).fetchall()]
                for col, definition in columns.items():
                    if col not in existing:
                        try:
                            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {definition}"))
                        except Exception:
                            pass

            ensure_columns('pengajuan_dokumentasi', {
                'user_id': "user_id INTEGER",
                'nomor_telpon': "nomor_telpon TEXT",
                'unit': "unit TEXT",
                'tanggal_acara': "tanggal_acara TEXT",
                'jam_mulai': "jam_mulai TEXT",
                'jam_selesai': "jam_selesai TEXT",
                'output_link_drive': "output_link_drive TEXT",
                'output_type': "output_type TEXT",
                'biaya': "biaya REAL DEFAULT 0",
                'deadline_penyelesaian': "deadline_penyelesaian TEXT",
                'status': "status TEXT DEFAULT 'pending'",
                'hasil_link_drive': "hasil_link_drive TEXT",
                'hasil_video': "hasil_video TEXT",
                'hasil_flyer': "hasil_flyer TEXT",
                'rejection_reason': "rejection_reason TEXT",
                'added_to_calendar': "added_to_calendar INTEGER DEFAULT 0",
                'created_at': "created_at TEXT",
                'updated_at': "updated_at TEXT",
                'notes': "notes TEXT"
            })

            ensure_columns('monitoring_pln', {
                'platform': "platform TEXT DEFAULT 'Instagram'",
                'tipe_konten': "tipe_konten TEXT DEFAULT 'Feeds'",
                'comments': "comments INTEGER DEFAULT 0",
                'source': "source TEXT DEFAULT 'Scraping'"
            })

            ensure_columns('dokumentasi_calendar', {
                'pengajuan_id': "pengajuan_id INTEGER",
                'tanggal': "tanggal TEXT",
                'nama_kegiatan': "nama_kegiatan TEXT",
                'unit': "unit TEXT",
                'status': "status TEXT",
                'doc_link': "doc_link TEXT",
                'created_at': "created_at TEXT"
            })
    except Exception as e:
        st.error(f"Database initialization error: {e}")

init_db()

# ============ GLOBAL CSS (ULTRA-COMPLETE PARIPURNA) ============
GLOBAL_CSS = """
<style>
/* [1] FONT & BASIC RESET */
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

* { 
    margin: 0; padding: 0; box-sizing: border-box; 
    font-family: 'Plus Jakarta Sans', sans-serif !important; 
}

:root { 
    --p: #2563eb; 
    --p-h: #1e40af; 
    --p-s: rgba(37, 99, 235, 0.05); 
    --bg: #fcfdfe; 
    --t-m: #0f172a; 
    --t-s: #64748b; 
}

/* [2] STREAMLIT UI HIDING (MEMBERSIHKAN LAYAR) */
[data-testid="stHeader"], header { display: none !important; }
[data-testid="stSidebar"] { border-right: 1px solid #f1f5f9 !important; }
[data-testid="stToolbar"], #MainMenu, footer { display: none !important; }

/* [3] MAIN CONTAINER (DEKET KE ATAS & RAPI) */
[data-testid="stAppViewContainer"] { background: var(--bg); }
[data-testid="stAppViewBlockContainer"] { 
    padding-top: 1.5rem !important; 
    padding-bottom: 5rem !important; 
    max-width: 1100px !important; 
    margin: 0 auto !important; 
}

/* [4] PAGE BOX & TITLES (GLASSMORPHISM HOVER) */
.page-box {
    background: white;
    border: 1px solid rgba(37,99,235,0.1);
    border-left: 6px solid var(--p);
    border-radius: 18px;
    padding: 30px 40px;
    margin-bottom: 30px !important;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.02);
    transition: all 0.4s ease;
}
.page-box:hover {
    transform: translateY(-4px);
    box-shadow: 0 15px 35px rgba(37,99,235,0.07);
    border-left-width: 10px;
}
.page-box h1 {
    color: var(--t-m) !important;
    font-size: 28px !important;
    font-weight: 800 !important;
    margin-bottom: 6px !important;
}
.page-subtitle {
    color: var(--t-s);
    font-size: 15px;
    font-weight: 500;
}

/* [5] FORM & INPUTS (ANTI DOUBLE BORDER) */
.stForm {
    background: white !important;
    padding: 40px !important;
    border-radius: 24px !important;
    border: 1px solid #f1f5f9 !important;
    box-shadow: 0 10px 40px rgba(0,0,0,0.03) !important;
}

/* Label Styling */
label[data-testid="stWidgetLabel"] p {
    font-weight: 700 !important;
    color: #475569 !important;
    font-size: 0.9rem !important;
    margin-bottom: 10px !important;
}

/* Fix untuk semua inputan */
.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea, div[data-baseweb="select"] {
    border-radius: 12px !important;
    border: 2px solid #f1f5f9 !important;
    background-color: #f8fafc !important;
    height: 48px !important;
    transition: all 0.2s ease !important;
}

/* MENGHILANGKAN DOUBLE BORDER PADA DROPDOWN */
div[data-baseweb="select"] > div {
    border: none !important; /* Hapus border dalem */
}
div[data-baseweb="select"]:focus-within {
    border-color: var(--p) !important;
    box-shadow: 0 0 0 4px var(--p-s) !important;
    background-color: white !important;
}

/* [6] BUTTONS (PREMIUM GRADIENT) */
.stButton > button {
    background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%) !important;
    color: white !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
    font-size: 15px !important;
    height: 52px !important;
    padding: 0 35px !important;
    border: none !important;
    box-shadow: 0 8px 15px rgba(37, 99, 235, 0.2) !important;
    transition: all 0.3s ease !important;
}
.stButton > button:hover {
    transform: translateY(-3px);
    box-shadow: 0 12px 25px rgba(37, 99, 235, 0.3) !important;
    filter: brightness(1.1);
}
/* [1] STYLE TOMBOL PEMBUKA EDIT (OUTLINE MODERN) */
.stButton > button[key^="btn_edit_"] {
    background-color: transparent !important;
    color: #2563eb !important;
    border: 2px solid #2563eb !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
    transition: all 0.3s ease !important;
}

.stButton > button[key^="btn_edit_"]:hover {
    background-color: #2563eb !important;
    color: white !important;
    transform: translateY(-2px);
}
div.stDownloadButton > button {
    background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%) !important;
    color: white !important;
    border: none !important;
    padding: 10px 20px !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    transition: all 0.3s ease !important;
}
div.stDownloadButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 12px rgba(34, 197, 94, 0.4) !important;
}
/* [2] CONTAINER AREA FORM (CARD STYLE) */
.edit-form-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 25px;
    margin-top: 15px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.05);
}
.stLinkButton > a {
    background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
    color: white !important;
    border-radius: 12px !important;
    font-weight: 800 !important;
    height: 52px !important;
    border: none !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    text-decoration: none !important;
    box-shadow: 0 6px 15px rgba(16, 185, 129, 0.2) !important;
    transition: all 0.3s ease !important;
}

.stLinkButton > a:hover {
    transform: translateY(-3px) !important;
    box-shadow: 0 10px 20px rgba(16, 185, 129, 0.3) !important;
    filter: brightness(1.1);
}

/* [1] PAKSA CONTAINER BIAR GAK MAKAN TEMPAT */
div[data-testid="stFormSubmitButton"] {
    display: flex !important;
    justify-content: flex-end !important; /* Geser ke kanan */
    width: 100% !important;
}

/* [2] PAKSA TOMBOL BIAR NGIKUTIN LEBAR TEKS (HUG CONTENT) */
div[data-testid="stFormSubmitButton"] button {
    width: auto !important; /* Hapus paksaan 100% */
    min-width: unset !important; /* Hapus minimal lebar */
    max-width: fit-content !important; /* Paksa pas sesuai teks */
    
    padding: 10px 25px !important; 
    background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%) !important;
    color: white !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: 14px !important;
    border: none !important;
    box-shadow: 0 4px 15px rgba(37, 99, 235, 0.2) !important;
    white-space: nowrap !important; /* Biar teks gak turun ke bawah */
}

/* HOVER EFFECT */
div[data-testid="stFormSubmitButton"] button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 20px rgba(37, 99, 235, 0.3) !important;
    filter: brightness(1.1);
}

/* [7] CARDS RIWAYAT (ELEGANT LIST) */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: white !important;
    border: 1px solid #f1f5f9 !important;
    border-radius: 20px !important;
    padding: 30px !important;
    margin-bottom: 20px !important;
    box-shadow: 0 2px 10px rgba(0,0,0,0.01) !important;
}

/* [8] EXPANDER & METRIC FIX */
.stExpander {
    border: 1px solid #f1f5f9 !important;
    border-radius: 14px !important;
    background: #fcfdfe !important;
}
[data-testid="stMetric"] {
    background: white !important;
    border: 1px solid #f1f5f9 !important;
    border-radius: 16px !important;
    padding: 20px !important;
}

/* Styling Metric agar lebih Bold */
[data-testid="stMetricValue"] {
    font-size: 1.8rem !important;
    font-weight: 800 !important;
    color: #1e293b !important;
}

[data-testid="stMetricLabel"] {
    font-weight: 600 !important;
    color: #64748b !important;
}

/* Card Styling untuk Kalender */
.calendar-card {
    background: white;
    padding: 10px;
    border-radius: 20px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.03);
}

/* Mempercantik Table DataFrame */
.stDataFrame {
    border-radius: 12px !important;
    overflow: hidden !important;
    border: 1px solid #f1f5f9 !important;
}

/* [9] SCROLLBAR STYLING (BIAR RAPI SAMPE DETAIL) */
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-track { background: #f1f5f9; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ============ HELPER FUNCTIONS SCRAP============
def clean_txt(text_input):
    if not text_input: return "Konten Visual"
    res = re.sub(r'[^\x00-\x7f]', r'', text_input)
    return res.replace('\n', ' ').strip()

def get_month_order():
    return ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 
            'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember']

def extract_username(input_str):
    if not input_str:
        return ""
    s = str(input_str).strip()
    # Jika merupakan URL posting (/p/shortcode) kembalikan full url (handler lain akan deteksi)
    if '/p/' in s:
        return s.rstrip('/')
    # Jika berupa URL profil, ambil username terakhir
    if 'instagram.com' in s:
        parts = s.rstrip('/').split('/')
        return parts[-1].replace('@','')
    # Jika berupa shortcode (beberapa input hanya shortcode), biarkan apa adanya
    return s.replace('@', '').strip()

def render_documentation_links(drive_link, video_link, flyer_link):
    """Render HTML untuk ketiga documentation links"""
    if not any([
        drive_link and pd.notna(drive_link) and str(drive_link).strip(),
        video_link and pd.notna(video_link) and str(video_link).strip(),
        flyer_link and pd.notna(flyer_link) and str(flyer_link).strip()
    ]):
        return "<div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(30, 58, 138, 0.1);'><div style='color: #94a3b8; font-size: 0.9rem; font-style: italic;'>📄 Dokumentasi belum tersedia</div></div>"
    
    html = "<div style='margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(30, 58, 138, 0.1);'><div style='display: flex; gap: 10px; flex-wrap: wrap;'>"
    
    if drive_link and pd.notna(drive_link) and str(drive_link).strip():
        html += f"<a href='{drive_link}' target='_blank' style='display: inline-block; background: #0ea5e9; color: white; padding: 8px 16px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 0.9rem;'>📁 Drive</a>"
    
    if video_link and pd.notna(video_link) and str(video_link).strip():
        html += f"<a href='{video_link}' target='_blank' style='display: inline-block; background: #f59e0b; color: white; padding: 8px 16px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 0.9rem;'>🎬 Video</a>"
    
    if flyer_link and pd.notna(flyer_link) and str(flyer_link).strip():
        html += f"<a href='{flyer_link}' target='_blank' style='display: inline-block; background: #8b5cf6; color: white; padding: 8px 16px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 0.9rem;'>📸 Flyer</a>"
    
    html += "</div></div>"
    return html


# ============ INSTAGRAM RATE LIMIT MANAGER ============
class InstagramRateLimitManager:
    """Manage Instagram rate limit safely with exponential backoff"""
    def __init__(self):
        self.last_request_time = {}
        self.rate_limit_wait_until = {}
        self.min_delay_between_requests = 3  # increased from 2 to 3 seconds
        self.user_agent_list = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
        ]
        self.ua_index = 0
        self.request_count = 0
    
    def get_next_user_agent(self):
        """Rotate user agents"""
        ua = self.user_agent_list[self.ua_index]
        self.ua_index = (self.ua_index + 1) % len(self.user_agent_list)
        return ua
    
    def wait_if_needed(self, username):
        """Check and wait if rate limit detected with jitter"""
        if username in self.rate_limit_wait_until:
            wait_until = self.rate_limit_wait_until[username]
            if datetime.now() < wait_until:
                remaining = (wait_until - datetime.now()).total_seconds()
                st.warning(f"⏳ Rate limit active untuk @{username}. Tunggu {int(remaining)} detik lagi...")
                time.sleep(min(remaining, 60))
        
        # Enforce minimum delay between requests dengan jitter
        if username in self.last_request_time:
            elapsed = (datetime.now() - self.last_request_time[username]).total_seconds()
            if elapsed < self.min_delay_between_requests:
                jitter = np.random.uniform(0.5, 1.5)  # Random jitter 0.5-1.5 seconds
                sleep_time = max(0, self.min_delay_between_requests - elapsed + jitter)
                time.sleep(sleep_time)
        
        self.last_request_time[username] = datetime.now()
        self.request_count += 1
    
    def mark_rate_limited(self, username, retry_after_seconds=900):
        """Mark account as rate limited (default 15 min)"""
        self.rate_limit_wait_until[username] = datetime.now() + timedelta(seconds=retry_after_seconds)
    
    def should_slow_down(self):
        """Return True if should add extra delay (every 10 requests)"""
        return self.request_count % 10 == 0 and self.request_count > 0

# Global rate limit manager
rate_limit_manager = InstagramRateLimitManager()

# Helper function to apply date filter
# ============ SCRAPER ENGINE ============
def run_scraper(username, unit_name, limit=20, target_month="Semua", kategori_input="Korporat", date_from=None, date_to=None, max_retries=2):
    """Scrape Instagram posts with retry logic and rate limit handling"""
    clean_username = extract_username(username)
    
    # Check cache first
    cache_key = f"{clean_username}_{unit_name}_{limit}_{target_month}"
    cached_result = scraping_cache.get(cache_key)
    if cached_result is not None:
        st.info(f"✅ Menggunakan cache untuk @{clean_username} (TTL: 1 jam)")
        return cached_result
    
    # Check rate limit before attempting
    rate_limit_manager.wait_if_needed(clean_username)
    
    L = instaloader.Instaloader()
    L.context.user_agent = rate_limit_manager.get_next_user_agent()
    
    results = []
    month_map = {i+1: m for i, m in enumerate(get_month_order())}
    
    # Normal profile scraping with retry and improved safety
    profile = None
    for attempt in range(max_retries + 1):
        try:
            # Rotate user agent setiap retry
            L.context.user_agent = rate_limit_manager.get_next_user_agent()
            profile = instaloader.Profile.from_username(L.context, clean_username)
            break
        except Exception as e:
            error_msg = str(e)
            # Check if user not found
            if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                st.error(f"❌ Username '@{clean_username}' tidak ditemukan")
                return pd.DataFrame()
            # Rate limit error
            elif "401 Unauthorized" in error_msg or "Please wait a few minutes" in error_msg or "429" in error_msg:
                rate_limit_manager.mark_rate_limited(clean_username)
                if attempt < max_retries:
                    wait_time = 10 * (2 ** attempt)  # Exponential backoff: 10s, 20s - lebih panjang untuk safety
                    st.warning(f"⏳ Instagram membatasi akses (Rate Limit). Menunggu {wait_time} detik sebelum retry... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    st.error(f"❌ Instagram membatasi akses setelah {max_retries} retry. Silakan coba lagi dalam 15-30 menit.")
                    return pd.DataFrame()
            else:
                st.error(f"❌ Gagal membuka profil @{clean_username}: {e}")
                return pd.DataFrame()
    
    if not profile:
        return pd.DataFrame()

    count = 0
    for post in profile.get_posts():
        try:
            if count >= limit:
                break

            cur_month = month_map.get(post.date.month, '')
            if target_month != "Semua" and cur_month != target_month:
                continue
            if date_from and post.date.date() < date_from:
                continue
            if date_to and post.date.date() > date_to:
                continue

            is_vid = getattr(post, 'is_video', False)
            caption = post.caption if getattr(post, 'caption', None) else ''
            results.append({
                "tanggal": post.date.strftime("%d/%m/%Y"),
                "bulan": cur_month,
                "tahun": str(post.date.year),
                "judul_pemberitaan": clean_txt(caption[:500] if caption else "Konten Visual"),
                "link_pemberitaan": f"https://www.instagram.com/p/{post.shortcode}/",
                "platform": "Instagram",
                "tipe_konten": "Reels" if is_vid else "Feeds",
                "pic_unit": unit_name,
                "akun": f"@{clean_username}",
                "kategori": kategori_input,
                "likes": int(getattr(post, 'likes', 0) or 0),
                "comments": int(getattr(post, 'comments', 0) or 0),
                "views": int(getattr(post, 'video_view_count', 0) or 0),
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "Scraping"
            })
            count += 1
            
            # Adaptive delay: lebih lama setiap beberapa post untuk safety
            base_delay = 2  # base delay 2 second
            if count % 5 == 0:
                # Extra delay every 5 posts
                extra_delay = np.random.uniform(1, 3)
                time.sleep(base_delay + extra_delay)
            else:
                time.sleep(base_delay)
        except Exception as inner_e:
            # Check if it's a rate limit error
            error_msg = str(inner_e)
            if "401 Unauthorized" in error_msg or "Please wait" in error_msg:
                rate_limit_manager.mark_rate_limited(clean_username)
                st.warning(f"⚠️ Rate limit detected saat scrape post. Menghentikan scraping untuk mencegah ban...")
                break
            else:
                # Skip problematic post but continue
                st.debug(f"Skip post @{clean_username}: {inner_e}")

    result_df = pd.DataFrame(results)
    # Cache the result
    scraping_cache.set(cache_key, result_df)
    return result_df

def apply_date_filter(df):
    """Apply date range filter to dataframe if enabled"""
    if not df.empty and st.session_state.get('use_date_filter', False):
        # Parse tanggal column
        df['tanggal_parsed'] = pd.to_datetime(df['tanggal'], format='%d/%m/%Y', errors='coerce')
        date_from = st.session_state.get('date_filter_from')
        date_to = st.session_state.get('date_filter_to')
        
        if date_from and date_to:
            df = df[(df['tanggal_parsed'] >= pd.Timestamp(date_from)) & 
                    (df['tanggal_parsed'] <= pd.Timestamp(date_to))]
            df = df.drop('tanggal_parsed', axis=1)
    return df

# --- Analytics / Export Helpers ---
def color_rekap_style(val):
    try:
        if val >= 20:
            color = '#002d40; color: white;'
        elif val >= 10:
            color = '#0072bc; color: white;'
        elif val > 0:
            color = '#f0f9ff; color: #0369a1;'
        else:
            color = 'white; color: #e2e8f0;'
    except Exception:
        color = 'white; color: #e2e8f0;'
    return f'background-color: {color}; font-weight: 600; border: 1px solid #f1f5f9'


def generate_excel_report(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        header_fmt = workbook.add_format({
            'bold': True,
            'font_color': '#ffffff',
            'bg_color': '#0072bc',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        year_title_fmt = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'font_color': '#0072bc',
            'underline': True
        })

        df.to_excel(writer, index=False, sheet_name='Data_Detail')
        worksheet1 = writer.sheets['Data_Detail']
        for col_num, value in enumerate(df.columns.values):
            worksheet1.write(0, col_num, value, header_fmt)
        worksheet1.set_column('A:Z', 18)

        if not df.empty:
            sheet_name = 'Rekapan Tahunan'
            worksheet2 = workbook.add_worksheet(sheet_name)

            daftar_tahun = sorted(df['tahun'].dropna().unique(), reverse=True)
            current_row = 0
            for thn in daftar_tahun:
                df_year = df[df['tahun'] == thn]

                rekap_thn = df_year.pivot_table(
                    index='pic_unit',
                    columns='bulan',
                    values='link_pemberitaan',
                    aggfunc='count',
                    fill_value=0
                )

                full_months = get_month_order()
                for m in full_months:
                    if m not in rekap_thn.columns:
                        rekap_thn[m] = 0
                rekap_thn = rekap_thn[full_months]

                worksheet2.write(current_row, 0, f"REKAPITULASI TAHUN {thn}", year_title_fmt)
                current_row += 1

                worksheet2.write(current_row, 0, 'Unit Kerja', header_fmt)
                for col_num, month_name in enumerate(rekap_thn.columns.values):
                    worksheet2.write(current_row, col_num + 1, month_name, header_fmt)

                data_row = current_row + 1
                for unit_idx, (unit_name, row_data) in enumerate(rekap_thn.iterrows()):
                    worksheet2.write(data_row + unit_idx, 0, unit_name)
                    for col_idx, val in enumerate(row_data):
                        worksheet2.write(data_row + unit_idx, col_idx + 1, val)

                current_row = data_row + len(rekap_thn) + 3

            worksheet2.set_column('A:A', 30)
            worksheet2.set_column('B:M', 12)

    return output.getvalue()

def get_nav_for_role(role):
    """Return navigation options based on user role"""
    if role == "admin":
        return ["Dashboard Admin", "Rekapitulasi Monitoring", "Sinkronisasi Data", "Input Manual",
                "Pengajuan Dokumentasi", "Kalender Dokumentasi", "Pengaturan Unit", "Manajemen User", "Pengaturan Admin"]
    else:  # user
        return ["Dashboard User", "Kalender Dokumentasi", "Pengajuan Dokumentasi", "Riwayat Dokumentasi"]

# ============ CALENDAR RENDER HELPERS ============

def parse_date_str(datestr):
    """Try to parse several date formats to a datetime.date object"""
    from datetime import datetime as _dt
    if not datestr or pd.isna(datestr):
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y"):
        try:
            return _dt.strptime(datestr, fmt).date()
        except Exception:
            continue
    try:
        # fallback: pandas
        return pd.to_datetime(datestr, dayfirst=True).date()
    except Exception:
        return None

def render_month_calendar(year, month, events=None):
    """Return HTML calendar for given month with events marked.

    events: list of dicts with keys 'tanggal' (str) and 'nama_kegiatan' and optional 'unit' and 'status'
    """
    cal = calendar.Calendar(firstweekday=6)  # week starts Sunday to mimic image
    weeks = cal.monthdayscalendar(year, month)
    events_map = {}
    if events is None:
        events = []
    for ev in events:
        d = parse_date_str(ev.get('tanggal'))
        if d and d.year == year and d.month == month:
            events_map.setdefault(d.day, []).append(ev)

    # Styles
    html = """
    <style>
    .mini-cal { 
        border-collapse: collapse; 
        width: 100%; 
        background: white;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        border: 1px solid #e2e8f0;
    }
    .mini-cal th { 
        background: linear-gradient(135deg, #0052a3 0%, #0a3a52 100%);
        color: white;
        padding: 12px 6px; 
        font-weight: 700;
        font-size: 13px;
        text-align: center;
    }
    .mini-cal td { 
        border: 1px solid #e2e8f0; 
        width: 14.28%; 
        vertical-align: top; 
        height: 110px; 
        padding: 8px; 
        background: #fff;
        position: relative;
    }
    .mini-cal td:hover {
        background: #f0f9ff;
    }
    .mini-cal .daynum { 
        font-weight: 700; 
        color: #0f172a;
        font-size: 14px;
        margin-bottom: 6px;
    }
    .event-badge { 
        display: block; 
        margin-top: 4px; 
        background: #e6f4ea; 
        color: #065f46; 
        padding: 4px 6px; 
        border-radius: 4px; 
        font-size: 11px;
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        border-left: 3px solid #10b981;
    }
    .event-badge.pending { 
        background: #fff7ed; 
        color: #92400e;
        border-left-color: #f59e0b;
    }
    .event-badge.approved { 
        background: #ecfdf5; 
        color: #065f46;
        border-left-color: #10b981;
    }
    .event-badge.done { 
        background: #edf2ff; 
        color: #312e81;
        border-left-color: #6366f1;
    }
    </style>
    """

    html += f"<table class='mini-cal'><thead><tr>"
    for wd in ['Ming', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab']:
        html += f"<th>{wd}</th>"
    html += "</tr></thead><tbody>"

    for week in weeks:
        html += "<tr>"
        for day in week:
            if day == 0:
                html += "<td style='background:#f8fafc;'></td>"
            else:
                html += "<td>"
                html += f"<div class='daynum'>{day}</div>"
                if day in events_map:
                    for ev in events_map[day][:2]:
                        status = ev.get('status', '').lower()
                        cls = 'event-badge ' + (status if status in ['pending', 'approved', 'done'] else '')
                        title = ev.get('nama_kegiatan', ev.get('unit', 'Kegiatan'))
                        html += f"<div class='{cls}' title='{title} ({status.upper()})'>{title[:20]}</div>"
                    if len(events_map[day]) > 2:
                        html += f"<div class='event-badge' style='background:#d1d5db;color:#374151;'>+{len(events_map[day])-2} lainnya</div>"
                html += "</td>"
        html += "</tr>"
    html += "</tbody></table>"
    return html

# ============ RENDER STICKY HEADER WITH NAVBAR ============
user_role = st.session_state.user.get('role', 'user')
user_name = st.session_state.user.get('username', 'User')

# Compatibility helper for different Streamlit versions: reliable rerun
def safe_rerun():
    try:
        st.rerun()
    except AttributeError:
        try:
            st.experimental_rerun()
        except Exception:
            st.stop()

# Ensure compatibility: if Streamlit doesn't provide `rerun`, alias it to our safe helper
if not hasattr(st, 'rerun'):
    st.rerun = safe_rerun

# Initialize navigation
nav_options = get_nav_for_role(user_role)
if st.session_state.current_nav is None:
    st.session_state.current_nav = nav_options[0]

# Render sticky header with logo and info
HEADER_CSS = """
<style>
/* Header / Navbar specific styles (kept next to header markup) */
.header-container { position: fixed; top: 0; left: 0; right: 0; width: 100%; background: linear-gradient(90deg, #60a5fa 0%, #3b82f6 100%); padding: 10px 20px; z-index: 2147483647 !important; box-shadow: 0 4px 12px rgba(8,30,60,0.08); border-bottom: 1px solid rgba(37,99,235,0.10); margin: 0; overflow: visible; pointer-events: auto; }
.header-content { max-width: 100%; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; gap: 30px; padding: 0; }
.header-logo { font-size: 17px; font-weight: 900; color: white; display: flex; align-items: center; gap: 8px; white-space: nowrap; letter-spacing: 0.5px; min-width: 180px; text-transform: uppercase; flex-shrink: 0; }
.header-info { display: flex; align-items: center; gap: 14px; flex: 1; min-width: 340px; }
.header-date, .header-user { background: rgba(255,255,255,0.12); color: white; padding: 8px 14px; border-radius: 8px; font-size: 11px; font-weight: 600; border: 1px solid rgba(255,255,255,0.18); white-space: nowrap; backdrop-filter: blur(10px); text-transform: uppercase; letter-spacing: 0.4px; }
.logout-btn { background: linear-gradient(90deg, #60a5fa 0%, #2563eb 100%); color: white; border: 1px solid rgba(37,99,235,0.16); padding: 8px 16px; border-radius: 8px; font-size: 11px; font-weight: 700; cursor: pointer; transition: all 0.2s ease; white-space: nowrap; text-transform: uppercase; letter-spacing: 0.3px; box-shadow: 0 2px 6px rgba(37,99,235,0.08); flex-shrink: 0; }
.logout-btn:hover { background: linear-gradient(90deg, #3b82f6 0%, #1d4ed8 100%); box-shadow: 0 4px 10px rgba(37,99,235,0.12); transform: translateY(-1px); }

/* small header helpers */
.nav-help { display:inline-block; border:1px dashed #cbd5e1; padding:8px 12px; border-radius:10px; color:#374151; background:#fbfdff; font-weight:700; margin-bottom:8px; }
.header-controls-row { display:flex; align-items:center; gap:12px; justify-content:flex-end; }

@media (max-width: 1024px) { .header-logo { font-size: 14px; min-width: 140px; } .nav-dropdown { flex: 0 1 200px; font-size: 10px; padding: 9px 12px; padding-right: 32px; } .logout-btn { padding: 9px 18px; font-size: 10px; } }
@media (max-width: 768px) { .header-content { flex-direction: column; gap: 12px; } .header-logo { width:100%; text-align:center; font-size:12px; } .header-nav { flex-direction:column; } .nav-dropdown, .logout-btn { width:100%; } }
</style>
"""
st.markdown(HEADER_CSS, unsafe_allow_html=True)

header_html = f"""
<div class='header-container' role='navigation' aria-label='App header'>
    <div class='header-content'>
        <div class='header-logo'>⚡ PLN UID LAMPUNG</div>
        <div class='header-info'>
            <div class='header-date'>📅 {datetime.now().strftime('%a, %d %b %Y')}</div>
            <div class='header-user'>👤 {user_name.upper()} | {user_role.upper()}</div>
        </div>
        <div class='header-nav' id='header-nav-controls'></div>
    </div>
</div>
"""
st.markdown(header_html, unsafe_allow_html=True)

# === NAVIGATION HEADER AREA ===
st.markdown('<div class="nav-wrapper">', unsafe_allow_html=True)

col_nav, col_out = st.columns([8, 2], vertical_alignment="bottom")

with col_nav:
    st.markdown("<p class='nav-help'>Pilih menu di sini</p>", unsafe_allow_html=True)
    
    current_nav_val = st.session_state.get('current_nav', nav_options[0] if nav_options else 'Dashboard')
    
    try:
        current_index = nav_options.index(current_nav_val)
    except (ValueError, IndexError):
        current_index = 0

    selected_nav = st.selectbox(
        label='Navigation Label',
        options=nav_options,
        index=current_index,
        key='nav_selectbox',
        label_visibility='collapsed' 
    )
    
    if selected_nav != st.session_state.get('current_nav'):
        st.session_state.current_nav = selected_nav
        st.rerun()

with col_out:
    if st.button('🚪 LOGOUT', key='logout_btn', use_container_width=True):
        st.session_state['confirm_logout'] = True

st.markdown('</div>', unsafe_allow_html=True)

if st.session_state.get('confirm_logout', False):
    st.markdown("<p style='color: #ef4444; font-weight: 700; margin: 8px 0 8px 0; font-size: 0.9rem;'>⚠️ Yakin ingin logout?</p>", unsafe_allow_html=True)
    logout_col1, logout_col2 = st.columns(2, gap="small")
    with logout_col1:
        if st.button("✅ Ya", use_container_width=True, key="confirm_logout_btn", type="primary"):
            if 'user' in st.session_state:
                del st.session_state['user']
            st.session_state.clear()
            st.toast("👋 Logout berhasil", icon="👋")
            time.sleep(0.5)
            st.rerun()
    with logout_col2:
        if st.button("❌ Batal", use_container_width=True, key="cancel_logout_btn", type="secondary"):
            st.session_state['confirm_logout'] = False
            st.rerun()

# Garis tipis pemisah konten agar lebih rapi (opsional)
st.markdown("<hr style='margin: 10px 0 25px 0; opacity: 0.1;'>", unsafe_allow_html=True)

# ============ ROLE-BASED PAGE ROUTING ============
nav = st.session_state.current_nav

# === ADMIN PAGES ===
if user_role == "admin":
    
    # ---------------------------------------------------------
    # PAGE 1: ADMIN DASHBOARD
    # ---------------------------------------------------------
    if nav == "Dashboard Admin":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>🏛️ Admin Command Center</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Monitoring Media Digital & Status Operasional Dokumentasi</p>
            </div>
        """, unsafe_allow_html=True)
        # Load Data
        df_main = pd.read_sql(text("SELECT * FROM monitoring_pln"), engine)
        df_req = pd.read_sql(text("SELECT * FROM pengajuan_dokumentasi"), engine)
        
        # --- ROW 1: EXECUTIVE SUMMARY (Metrics) ---
        with st.container(border=True):
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("TOTAL POST 🖋️", len(df_main))
            m2.metric("TOTAL LIKES ❤️", f"{int(df_main['likes'].sum()):,}")
            m3.metric("TOTAL VIEWS 👀", f"{int(df_main['views'].sum()):,}")
            m4.metric("PENGAJUAN 📩", len(df_req))
            m5.metric("UNIT AKTIF 📝", df_main['pic_unit'].nunique())

        st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)

        # --- ROW 2: GRAFIK ANALISIS (3 KOLOM SEJAJAR) ---
        # Kita buat 3 kolom supaya grafik lama dan status dokumentasi sejajar presisi
        col_a, col_b, col_c = st.columns([1, 1, 1], gap="small")
        
        with col_a:
            st.markdown("<h5 style='font-weight:800;'>📈 Tren Publikasi</h5>", unsafe_allow_html=True)
            with st.container(border=True, height=270):
                # GRAFIK LAMA 1: Tren Bulanan
                counts = df_main['bulan'].value_counts().reindex(get_month_order()).fillna(0)
                st.area_chart(counts, color="#2563eb", height=250)

        with col_b:
            st.markdown("<h5 style='font-weight:800;'>🏆 Top 5 Unit</h5>", unsafe_allow_html=True)
            with st.container(border=True, height = 270):
                # GRAFIK LAMA 2: Bar Chart Unit
                unit_counts = df_main['pic_unit'].value_counts().head(5)
                st.bar_chart(unit_counts, color="#3b82f6", height=250)

        with col_c:
            st.markdown("<h5 style='font-weight:800;'>📊 Status Dokumentasi</h5>", unsafe_allow_html=True)
            with st.container(border=True, height = 270):
                # GRAFIK BARU: Rekap Status Pengajuan
                if not df_req.empty:
                    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                    for label, status_key, color in [("Done ✅", "done", "green"), ("Approved 🚀", "approved", "blue"), ("Pending ⏳", "pending", "orange")]:
                        count = len(df_req[df_req['status'] == status_key])
                        pct = count/len(df_req)
                        st.write(f"<small><b>{label}</b>: {count}</small>", unsafe_allow_html=True)
                        st.progress(pct)
                else:
                    st.info("Tidak ada data pengajuan")

        st.markdown("<div style='margin-top:30px;'></div>", unsafe_allow_html=True)

        # --- ROW 3: REKAPITULASI DETAIL (TABS) ---
        tab_top, tab_recent, tab_finance = st.tabs(["⭐ Top Akun Sosmed", "📝 Pengajuan Terbaru", "💎 Rekap Biaya Unit"])

        with tab_top:
            st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
            top_acc = df_main.groupby(['akun', 'pic_unit']).agg({'link_pemberitaan': 'count', 'likes': 'sum', 'views': 'sum'}).rename(columns={'link_pemberitaan': 'Post', 'likes': 'Likes', 'views': 'Views'}).sort_values('Post', ascending=False).head(10)
            st.dataframe(top_acc, use_container_width=True)

        with tab_recent:
            st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
            if not df_req.empty:
                df_req_show = df_req.sort_values('created_at', ascending=False).head(10)[['id','created_at','tanggal_acara','nama_pengaju','unit','nomor_telpon','deadline_penyelesaian','biaya','status']]
                # format biaya
                if 'biaya' in df_req_show.columns:
                    df_req_show['biaya'] = df_req_show['biaya'].fillna(0).apply(lambda x: f"Rp {int(x):,}")
                st.dataframe(df_req_show, use_container_width=True, hide_index=True)

        with tab_finance:
            st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
            if not df_req.empty:
                finance_unit = df_req.groupby('unit')['biaya'].sum().reset_index().sort_values('biaya', ascending=False)
                st.dataframe(finance_unit, use_container_width=True, hide_index=True, column_config={"biaya": st.column_config.NumberColumn("Total Biaya", format="Rp %d")})

    # ---------------------------------------------------------
    # PAGE 2: REKAPITULASI MONITORING (DASHBOARD & EDITOR)
    # ---------------------------------------------------------
    elif nav == "Rekapitulasi Monitoring":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>📈 Rekapitulasi Monitoring</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Pusat Data dan Audit Konten Terintegrasi</p>
            </div>
        """, unsafe_allow_html=True)

        # Load Database Utama
        try:
            df_db = pd.read_sql(text("SELECT * FROM monitoring_pln"), engine)
            if df_db.empty:
                st.info("ℹ️ Database monitoring kosong. Silakan lakukan sinkronisasi data terlebih dahulu.")
        except Exception as e:
            st.error(f"❌ Gagal membaca database: {e}")
            df_db = pd.DataFrame()
        
        # Pre-processing Data agar Filter Akurat
        if not df_db.empty:
            df_db['pic_unit'] = df_db['pic_unit'].fillna("Unknown")
            df_db['kategori'] = df_db['kategori'].fillna("Korporat")
            df_db['tahun'] = df_db['tahun'].astype(str)
            # Normalize "bulan" values: strip whitespace and convert numeric months to month names
            try:
                df_db['bulan'] = df_db['bulan'].fillna('').astype(str).str.strip()
                def _normalize_month(val):
                    try:
                        v = str(val).strip()
                        if v.isdigit():
                            m = int(v)
                            if 1 <= m <= 12:
                                return get_month_order()[m-1]
                        # handle numeric like '01'
                        if len(v) == 2 and v.isdigit():
                            m = int(v)
                            if 1 <= m <= 12:
                                return get_month_order()[m-1]
                        return v
                    except Exception:
                        return val
                df_db['bulan'] = df_db['bulan'].apply(_normalize_month)
            except Exception:
                pass

            st.info(f"📊 Memuat {len(df_db)} data dari database")

        # --- SECTION: FILTER PANEL ---
        if df_db.empty:
            st.warning("⚠️ Tidak ada data untuk ditampilkan. Lakukan sinkronisasi terlebih dahulu.")
        else:
            with st.container():
                st.markdown("<div style='background: white; padding: 20px; border-radius: 15px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); margin-bottom: 20px;'>", unsafe_allow_html=True)
                st.markdown("<p style='font-weight:700; color:#1e3a8a; margin-bottom:15px;'>🔍 SMART FILTERING</p>", unsafe_allow_html=True)
                
                f1, f2, f3, f4, f5 = st.columns([1.2, 1, 1, 1, 1])
                with f1:
                    search_judul = st.text_input("Kata Kunci", placeholder="Cari caption...")
                with f2:
                    list_unit = ["Semua Unit"] + sorted(df_db['pic_unit'].unique().tolist())
                    sel_unit = st.selectbox("Unit Kerja", list_unit)
                with f3:
                    list_akun = ["Semua Akun"] + sorted(df_db['akun'].unique().tolist())
                    sel_akun = st.selectbox("Akun", list_akun)
                with f4:
                    sel_kat = st.selectbox("Kategori", ["Semua", "Korporat", "Influencer"])
                with f5:
                    list_src = ["Semua"] + sorted(df_db['source'].fillna('Scraping').unique().tolist())
                    sel_source = st.selectbox("Sumber Data", list_src)

                # Filter Logic
                df_filtered = df_db.copy()
                if search_judul:
                    df_filtered = df_filtered[df_filtered['judul_pemberitaan'].str.contains(search_judul, case=False, na=False)]
                if sel_unit != "Semua Unit":
                    df_filtered = df_filtered[df_filtered['pic_unit'] == sel_unit]
                if sel_akun != "Semua Akun":
                    df_filtered = df_filtered[df_filtered['akun'] == sel_akun]
                if sel_kat != "Semua":
                    df_filtered = df_filtered[df_filtered['kategori'] == sel_kat]
                if 'sel_source' in locals() and sel_source != "Semua":
                    df_filtered = df_filtered[df_filtered['source'] == sel_source]
                
                st.markdown("</div>", unsafe_allow_html=True)

            # Apply Global Date Filter (Asumsi fungsi ini ada di helper-mu)
            df_display = apply_date_filter(df_filtered)
            
            if not df_display.empty:
                # --- SECTION: ACTIONS ---
                c_stat, c_dl = st.columns([2, 1])
                with c_stat:
                    st.markdown(f"""
                        <div style='background-color: #f0fdf4; border-left: 5px solid #22c55e; padding: 12px; border-radius: 8px;'>
                            <span style='color: #166534; font-weight: 600;'>✓ Berhasil memfilter {len(df_display)} data postingan.</span>
                        </div>
                    """, unsafe_allow_html=True)
                with c_dl:
                    st.download_button(
                        label="📥 DOWNLOAD EXCEL",
                        data=generate_excel_report(df_display),
                        file_name=f"Rekap_PLN_{datetime.now().strftime('%d%m%y')}.xlsx",
                        use_container_width=True
                    )

                st.markdown("<br>", unsafe_allow_html=True)

                # --- SECTION: CONTENT TABS ---
                t_heatmap, t_editor = st.tabs(["📊 VISUALISASI HEATMAP", "📑 DATABASE EDITOR"])
                
                with t_heatmap:
                    st.markdown("<div style='background: white; padding: 20px; border-radius: 15px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);'>", unsafe_allow_html=True)
                    years_sorted = sorted(df_display['tahun'].unique().tolist(), reverse=True)

                    if years_sorted:
                        y_tabs = st.tabs(["Semua Tahun"] + years_sorted)
                        for i, y_val in enumerate(["Semua Tahun"] + years_sorted):
                            with y_tabs[i]:
                                df_y = df_display if y_val == "Semua Tahun" else df_display[df_display['tahun'] == y_val]
                                if not df_y.empty:
                                    pivot = df_y.pivot_table(index='pic_unit', columns='bulan', values='link_pemberitaan', aggfunc='count', fill_value=0)
                                    bulan_order = [b for b in get_month_order() if b in pivot.columns]
                                    if bulan_order:
                                        st.dataframe(pivot[bulan_order].style.background_gradient(cmap='GnBu', axis=None), use_container_width=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                with t_editor:
                    st.markdown("<div style='background: white; padding: 20px; border-radius: 15px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);'>", unsafe_allow_html=True)
                    st.info("💡 Klik dua kali pada sel untuk mengedit. Pilih  kolom dan tekan delete di keyboard untuk menghapus. Gunakan tombol simpan di bawah untuk memperbarui database.")
                    
                    # Kolom yang ditampilkan di editor (urut sesuai permintaan pengguna)
                    display_cols = [
                        'tanggal', 'bulan', 'tahun', 'judul_pemberitaan', 'link_pemberitaan',
                        'kategori', 'likes', 'views', 'comments', 'last_updated', 'pic_unit', 'akun', 'platform'
                    ]

                    # Pastikan kolom `platform` ada untuk kompatibilitas DB lama
                    if 'platform' not in df_display.columns:
                        df_display['platform'] = 'Instagram'

                    ed = st.data_editor(

                        df_display[display_cols],
                        use_container_width=True,
                        hide_index=True,
                        num_rows="dynamic",
                        disabled=["last_updated"],
                        column_config={
                            "tanggal": st.column_config.TextColumn("Tanggal", width="small"),
                            "bulan": st.column_config.SelectboxColumn("Bulan", options=get_month_order()),
                            "tahun": st.column_config.TextColumn("Tahun", width="small"),
                            "judul_pemberitaan": st.column_config.TextColumn("Judul Pemberitaan", width="large"),
                            "link_pemberitaan": st.column_config.LinkColumn("Link Post"),
                            "kategori": st.column_config.SelectboxColumn("Kategori", options=["Korporat", "Influencer", "Kampanye"]),
                            "likes": st.column_config.NumberColumn("Likes", format="%d"),
                            "views": st.column_config.NumberColumn("Views", format="%d"),
                            "comments": st.column_config.NumberColumn("Comments", format="%d"),
                            "last_updated": st.column_config.TextColumn("Last Updated", disabled=True),
                            "pic_unit": st.column_config.TextColumn("Unit", width="medium"),
                            "akun": st.column_config.TextColumn("Akun", width="medium"),
                            "platform": st.column_config.SelectboxColumn("Platform", options=["Instagram", "Facebook", "TikTok", "Twitter", "YouTube"])
                        }
                    )
                    
                    if st.button("💾 SIMPAN KE DATABASE", use_container_width=True, type="primary"):
                        with st.spinner("Mengupdate database..."):
                            try:
                                ed['likes'] = pd.to_numeric(ed['likes']).fillna(0).astype(int)
                                ed['comments'] = pd.to_numeric(ed['comments']).fillna(0).astype(int)
                                ed['views'] = pd.to_numeric(ed['views']).fillna(0).astype(int)

                                with engine.begin() as conn:
                                    # 1) Detect deleted rows by link comparison
                                    if len(ed) < len(df_display):
                                        original_links = set(df_display['link_pemberitaan'].astype(str).fillna(''))
                                        edited_links = set(ed['link_pemberitaan'].astype(str).fillna(''))
                                        deleted_links = [l for l in original_links - edited_links if l and l.strip()]
                                        
                                        # Delete each removed row individually
                                        for link_del in deleted_links:
                                            try:
                                                conn.execute(text("DELETE FROM monitoring_pln WHERE link_pemberitaan = :lk"), {"lk": link_del})
                                            except Exception:
                                                pass

                                    # 2) Upsert remaining/edited rows
                                    for _, row in ed.iterrows():
                                        # Ambil nilai dari row dan juga padankan tahun jika tidak ada (ambil dari df_display)
                                        link = row.get('link_pemberitaan')
                                        # find source row in df_display to retrieve 'tahun' if needed
                                        src = df_display[df_display['link_pemberitaan'] == link]
                                        tahun_val = None
                                        if not src.empty and 'tahun' in src.columns:
                                            tahun_val = str(src.iloc[0].get('tahun'))

                                        params = {
                                            "t": row.get('tanggal'),
                                            "b": row.get('bulan'),
                                            "y": tahun_val or datetime.now().year,
                                            "j": row.get('judul_pemberitaan'),
                                            "l": row.get('link_pemberitaan'),
                                            "pic": row.get('pic_unit'),
                                            "ak": row.get('akun'),
                                            "kat": row.get('kategori'),
                                            "lk": int(row.get('likes') or 0),
                                            "cm": int(row.get('comments') or 0),
                                            "vw": int(row.get('views') or 0),
                                            "lu": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                        }

                                        conn.execute(text("""
                                            INSERT INTO monitoring_pln (
                                                tanggal, bulan, tahun, judul_pemberitaan, link_pemberitaan,
                                                pic_unit, akun, kategori, likes, comments, views, last_updated
                                            ) VALUES (
                                                :t, :b, :y, :j, :l,
                                                :pic, :ak, :kat, :lk, :cm, :vw, :lu
                                            )
                                            ON CONFLICT(link_pemberitaan) DO UPDATE SET
                                                tanggal=excluded.tanggal,
                                                bulan=excluded.bulan,
                                                tahun=excluded.tahun,
                                                judul_pemberitaan=excluded.judul_pemberitaan,
                                                pic_unit=excluded.pic_unit,
                                                akun=excluded.akun,
                                                kategori=excluded.kategori,
                                                likes=excluded.likes,
                                                comments=excluded.comments,
                                                views=excluded.views,
                                                last_updated=excluded.last_updated
                                        """), params)

                                st.success("Database Terupdate!")
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                    st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.warning("Data tidak ditemukan untuk kriteria filter tersebut.")

    # ---------------------------------------------------------
    # PAGE 3: SINKRONISASI DATA (LOGIKA PENARIKAN DATA)
    # ---------------------------------------------------------
    elif nav == "Sinkronisasi Data":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>🔄 Sinkronisasi Data</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Automasi Penarikan Data Instagram Korporat & Influencer</p>
            </div>
        """, unsafe_allow_html=True)
        
        units_df = pd.read_sql(text("SELECT * FROM daftar_akun_unit"), engine)
        
        # --- 1. METRIC SECTION ---
        try:
            db_info = pd.read_sql(text("SELECT COUNT(*) as total, MAX(last_updated) as terakhir FROM monitoring_pln"), engine)
            total_data = db_info['total'][0]
            last_up = str(db_info['terakhir'][0])[:16] if db_info['terakhir'][0] else "-"
        except:
            total_data, last_up = 0, "-"
        
        m1, m2, m3 = st.columns(3)
        metrics = [
            {"label": "UNIT TERDAFTAR", "val": f"{len(units_df)} Akun", "color": "#0ea5e9"},
            {"label": "TOTAL DATABASE", "val": f"{total_data} Post", "color": "#10b981"},
            {"label": "UPDATE TERAKHIR", "val": last_up, "color": "#f59e0b"}
        ]
        for i, m in enumerate([m1, m2, m3]):
            m.markdown(f"""
                <div style='background: white; padding: 20px; border-radius: 15px; border-left: 5px solid {metrics[i]['color']}; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);'>
                    <p style='color: #64748b; margin: 0; font-size: 12px; font-weight: 700; text-transform: uppercase;'>{metrics[i]['label']}</p>
                    <h3 style='color: #1e3a8a; margin: 5px 0 0 0; font-size: 18px;'>{metrics[i]['val']}</h3>
                </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # --- 2. CONFIGURATION PANEL ---
        with st.container(border=True):
            st.markdown("<h4 style='color: #1e3a8a; margin-top: 0;'>⚙️ Pengaturan Sinkronisasi</h4>", unsafe_allow_html=True)
            
            cc1, cc2, cc3, cc4 = st.columns([1.5, 1, 0.8, 1])
            sync_mode = cc1.selectbox("Target Sinkronisasi", 
                ["Semua Akun Terdaftar", "Pilih Akun Unit Spesifik", "Input Manual Username Influencer"])
            sync_month = cc2.selectbox("Filter Bulan", ["Semua"] + ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"])
            sync_limit = cc3.number_input("Limit Post", 1, 100, 10)
            date_mode = cc4.selectbox("Mode Periode", ["Semua Waktu", "Custom Range"])

            date_from, date_to = None, None
            if date_mode == "Custom Range":
                cd1, cd2 = st.columns(2)
                date_from = cd1.date_input("Dari Tanggal", value=datetime.now().replace(day=1))
                date_to = cd2.date_input("Sampai Tanggal")

            # Logika Penentuan Target (Dataframe to_process)
            to_process = pd.DataFrame()
            if sync_mode == "Input Manual Username Influencer":
                ci1, ci2 = st.columns(2)
                inf_user = ci1.text_input("Username IG", placeholder="jeromepolin")
                inf_unit = ci2.selectbox("Kaitkan ke Unit", units_df['nama_unit'].tolist() if not units_df.empty else ["Pusat"])
                if inf_user:
                    to_process = pd.DataFrame([{"username_ig": inf_user.replace('@','').strip(), "nama_unit": inf_unit, "kategori": "Influencer"}])
            
            elif sync_mode == "Pilih Akun Unit Spesifik":
                sel_acc = st.multiselect("Pilih Akun Unit", units_df['username_ig'].tolist())
                to_process = units_df[units_df['username_ig'].isin(sel_acc)].copy()
                to_process['kategori'] = "Korporat"
                
            else:
                to_process = units_df.copy()
                to_process['kategori'] = "Korporat"

            # --- EXECUTION ENGINE ---
            if st.button("🚀 MULAI PROSES SINKRONISASI", use_container_width=True, type="primary"):
                if to_process.empty:
                    st.error("❌ Pilih target dulu!")
                else:
                    log_box = st.empty()
                    prog_bar = st.progress(0)
                    
                    inserted = 0
                    updated = 0
                    for idx, row in to_process.iterrows():
                        target = row.get('username_ig', '')
                        unit_name = row.get('nama_unit', 'Unknown')
                        kat_name = row.get('kategori', 'Korporat')

                        log_box.info(f"🔄 Memproses: `@{target}`...")
                        try:
                            # Scrape data dari username/profil
                            new_data_df = run_scraper(target, unit_name, sync_limit, sync_month, kat_name, date_from, date_to)
                            new_data_list = new_data_df.to_dict('records') if not new_data_df.empty else []

                            # Simpan dengan logika insert/update eksplisit untuk menghitung berapa yang baru/diupdate
                            if new_data_list:
                                try:
                                    with engine.begin() as conn:
                                        for item in new_data_list:
                                            if not item: continue
                                            link = item.get('link_pemberitaan')
                                            if not link:
                                                st.warning(f"⚠️ Skip item tanpa link: {item.get('judul_pemberitaan', 'Unknown')[:50]}")
                                                continue
                                            # cek ada tidaknya record
                                            exists = conn.execute(text("SELECT id FROM monitoring_pln WHERE link_pemberitaan = :l"), {"l": link}).fetchone()
                                            if exists:
                                                conn.execute(text("""
                                                    UPDATE monitoring_pln SET 
                                                        tanggal=:t, bulan=:b, tahun=:y, judul_pemberitaan=:j,
                                                        platform=:p, tipe_konten=:tk, pic_unit=:pic, akun=:ak, kategori=:kat,
                                                        likes=:lk, comments=:cm, views=:vw, last_updated=:lu, source=:src
                                                    WHERE link_pemberitaan = :l
                                                """), {
                                                    "t": item.get('tanggal'), "b": item.get('bulan'), "y": str(item.get('tahun')),
                                                    "j": item.get('judul_pemberitaan', 'No Title'), "p": item.get('platform', 'Instagram'),
                                                    "tk": item.get('tipe_konten', 'Feeds'), "pic": unit_name, "ak": item.get('akun', target),
                                                    "kat": kat_name, "lk": int(item.get('likes',0)), "cm": int(item.get('comments',0)),
                                                    "vw": int(item.get('views',0)), "lu": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                                                    "src": item.get('source', 'Scraping'), "l": link
                                                })
                                                updated += 1
                                            else:
                                                conn.execute(text("""
                                                    INSERT INTO monitoring_pln (
                                                        tanggal, bulan, tahun, judul_pemberitaan, link_pemberitaan,
                                                        platform, tipe_konten, pic_unit, akun, kategori,
                                                        likes, comments, views, last_updated, source
                                                    ) VALUES (
                                                        :t, :b, :y, :j, :l, :p, :tk, :pic, :ak, :kat, :lk, :cm, :vw, :lu, :src
                                                    )
                                                """), {
                                                    "t": item.get('tanggal'), "b": item.get('bulan'), "y": str(item.get('tahun')),
                                                    "j": item.get('judul_pemberitaan', 'No Title'), "l": link,
                                                    "p": item.get('platform', 'Instagram'), "tk": item.get('tipe_konten', 'Feeds'),
                                                    "pic": unit_name, "ak": item.get('akun', target), "kat": kat_name,
                                                    "lk": int(item.get('likes', 0)), "cm": int(item.get('comments', 0)),
                                                    "vw": int(item.get('views', 0)), "lu": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                                    "src": item.get('source', 'Scraping')
                                                })
                                                inserted += 1
                                except Exception as inner_e:
                                    st.error(f"❌ Gagal insert/update item: {inner_e}")
                                    continue

                            # Update progress bar dengan value dalam range [0, 1]
                            progress_value = min((idx + 1) / len(to_process), 1.0)
                            prog_bar.progress(progress_value)
                        except Exception as e:
                            st.warning(f"⚠️ Skip @{target}: {str(e)}")
                            # Update progress bar meskipun ada error
                            progress_value = min((idx + 1) / len(to_process), 1.0)
                            prog_bar.progress(progress_value)

                    # Summary after processing
                    st.balloons()
                    st.success(f"Sinkronisasi selesai — Baru: {inserted}, Diperbarui: {updated}")
                    
                    st.success("✅ Sinkronisasi Selesai!")
                    time.sleep(2)
                    st.cache_data.clear()  # Clear cache untuk reload data
                    st.rerun()

    # ---------------------------------------------------------
    # PAGE 4: INPUT DATA (FORM & SCRAPE)
    # ---------------------------------------------------------
    elif nav == "Input Manual":
        # Header Utama
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px;'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>✏️ Input Data Manual</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Tambahkan Data Monitoring Secara Manual atau via Link Postingan</p>
            </div>
        """, unsafe_allow_html=True)
        
        # Ambil daftar unit untuk selectbox
        units_list = pd.read_sql(text("SELECT nama_unit FROM daftar_akun_unit"), engine)['nama_unit'].tolist()
        
        # Hanya Form Manual — scraping via link hanya di halaman Sinkronisasi
        st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown("<p style='font-weight:700; color:#1e3a8a;'>Entry Data Baru</p>", unsafe_allow_html=True)
                
                with st.form("form_manual_admin", clear_on_submit=True):
                    m_kat = st.radio("Jenis Konten", ["Korporat", "Influencer"], horizontal=True)
                    
                    st.markdown("---")
                    f1, f2 = st.columns(2)
                    m_tgl = f1.date_input("📅 Tanggal Konten")
                    m_plat = f2.selectbox("📱 Platform", ["Instagram", "YouTube", "Facebook", "Twitter", "TikTok", "Media Cetak", "Berita"])
                    
                    m_judul = st.text_area("📝 Caption / Judul Konten", placeholder="Ketik caption lengkap di sini...")
                    m_link = st.text_input("🔗 Link URL", placeholder="https://instagram.com/p/...")
                    
                    f3, f4, f5 = st.columns(3)
                    with f3:
                        m_unit = st.selectbox("🏢 Unit Kerja", units_list) if units_list else st.text_input("Unit Kerja")
                    with f4:
                        m_akun = st.text_input("👤 Nama Akun", placeholder="@username")
                    with f5:
                        m_tipe = st.selectbox("📂 Tipe Konten", ["Feeds", "Reels", "Postingan"])
                    
                    st.markdown("<p style='font-size: 13px; color: #64748b; margin-top: 10px;'>Statistik Performa:</p>", unsafe_allow_html=True)
                    f6, f7, f8 = st.columns(3)
                    m_lk = f6.number_input("❤️ Likes", min_value=0, step=1)
                    m_cm = f7.number_input("💬 Comments", min_value=0, step=1)
                    m_vw = f8.number_input("👁️ Views", min_value=0, step=1)
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    btn_save = st.form_submit_button("💾 SIMPAN KE DATABASE", use_container_width=True)
                    
                    if btn_save:
                        if m_unit and m_akun:
                            ml = get_month_order()
                            nama_bulan = ml[m_tgl.month - 1]
                            
                            # Generate link jika kosong (untuk UNIQUE constraint)
                            if not m_link or m_link.strip() == '':
                                m_link = f"https://manual-input-{datetime.now().timestamp()}/"
                            
                            try:
                                with engine.begin() as conn:
                                    # Cek apakah link sudah ada
                                    existing = conn.execute(text("SELECT id FROM monitoring_pln WHERE link_pemberitaan = :l"), {"l": m_link}).fetchone()

                                    # Jika link sudah ada, jangan menimpanya — buat link unik untuk input manual
                                    link_to_save = m_link
                                    if existing:
                                        suffix = f"-manual-{int(datetime.now().timestamp())}"
                                        # pastikan bukan menimbulkan konflik lagi
                                        link_to_save = (m_link.rstrip('/') + suffix)

                                    # Insert baru dengan marker source
                                    conn.execute(text("""
                                        INSERT INTO monitoring_pln (
                                            tanggal, bulan, tahun, judul_pemberitaan, link_pemberitaan,
                                            platform, tipe_konten, pic_unit, akun, kategori, likes, comments, views, last_updated, source
                                        )
                                        VALUES (:t, :b, :y, :j, :l, :p, :tk, :pic, :ak, :kat, :lk, :cm, :vw, :lu, :src)
                                    """), {
                                        "t": m_tgl.strftime("%d/%m/%Y"), "b": nama_bulan, "y": str(m_tgl.year),
                                        "j": clean_txt(m_judul), "l": link_to_save, "p": m_plat, "tk": m_tipe,
                                        "pic": m_unit, "ak": m_akun, "kat": m_kat, "lk": m_lk, "cm": m_cm, "vw": m_vw,
                                        "lu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "src": "Input Manual"
                                    })
                                st.balloons()
                                st.success(f"✅ Berhasil menyimpan data {m_kat}!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Gagal menyimpan data: {e}")
                        else:
                            st.error("⚠️ Mohon lengkapi Akun dan Unit Kerja. Link bersifat opsional untuk input manual.")

        # Note: scraping from link intentionally removed from manual input page.

    # ---------------------------------------------------------
    # PAGE 4: PUSAT KENDALI PENGADAAN DOKUMENTASI (ADMIN)
    # ---------------------------------------------------------
    elif nav == "Pengajuan Dokumentasi":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>📋 Pusat Kendali Dokumentasi</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Review data pengajuan dan manajemen link hasil aset digital.</p>
            </div>
        """, unsafe_allow_html=True)

        df_admin = pd.read_sql(text("SELECT * FROM pengajuan_dokumentasi ORDER BY id DESC"), engine)

        if df_admin.empty:
            st.info("ℹ️ Belum ada pengajuan masuk.")
        else:
            # --- PANEL FILTER  ---
            with st.container(border=True):
                f1, f2, f3 = st.columns([1, 1, 1.5])
                status_filter = f1.selectbox("🎯 Filter Status", ["Semua", "pending", "approved", "done", "rejected"])
                unit_filter = f2.selectbox("🏢 Filter Unit", ["Semua"] + sorted(list(df_admin['unit'].unique())))
                search_query = f3.text_input("🔍 Cari Nama Kegiatan", placeholder="Ketik kata kunci...")

                if status_filter != "Semua": df_admin = df_admin[df_admin['status'] == status_filter]
                if unit_filter != "Semua": df_admin = df_admin[df_admin['unit'] == unit_filter]
                if search_query: df_admin = df_admin[df_admin['nama_pengaju'].str.contains(search_query, case=False, na=False)]

        # --- LOOPING KARTU PENGAJUAN ---
        for _, row in df_admin.iterrows():
            st_color = {"pending": "#f59e0b", "approved": "#10b981", "done": "#3b82f6", "rejected": "#ef4444"}.get(row['status'].lower(), "#64748b")
            is_rejected = row['status'].lower() == 'rejected'
            
            with st.container(border=True):
                st.markdown(f"""
                    <div style='display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #f1f5f9; padding-bottom: 12px; margin-bottom: 20px;'>
                        <div style='font-size: 18px; font-weight: 800; color: #1e3a8a;'>ID #{row['id']} | {row['nama_pengaju']}</div>
                        <div style='background: {st_color}; color: white; padding: 6px 16px; border-radius: 8px; font-size: 12px; font-weight: 900; letter-spacing: 1px;'>{row['status'].upper()}</div>
                    </div>
                """, unsafe_allow_html=True)

                st.markdown("<p style='font-weight: 800; color: #64748b; font-size: 11px; margin-bottom:10px; text-transform: uppercase;'>🔘 Informasi Dasar</p>", unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns(4)
                c1.text_input("🏢 Unit Kerja", value=row['unit'], disabled=True, key=f"u_{row['id']}")
                c2.text_input("👤 Nama Pengaju", value=row['nama_pengaju'].split(' - ')[-1], disabled=True, key=f"p_{row['id']}")
                c3.text_input("📱 WhatsApp", value=row['nomor_telpon'], disabled=True, key=f"w_{row['id']}")
                c4.text_input("💰 Estimasi Biaya", value=f"Rp {int(row.get('biaya') or 0):,}", disabled=True, key=f"b_{row['id']}")

                st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
                st.markdown("<p style='font-weight: 800; color: #64748b; font-size: 11px; margin-bottom:10px; text-transform: uppercase;'>📅 Jadwal & Referensi</p>", unsafe_allow_html=True)
                d1, d2, d3, d4 = st.columns(4)
                d1.text_input("📅 Tanggal Acara", value=row['tanggal_acara'], disabled=True, key=f"t_{row['id']}")
                d2.text_input("🕐 Waktu", value=f"{row['jam_mulai']} - {row['jam_selesai']}", disabled=True, key=f"j_{row['id']}")
                d3.text_input("🏁 Deadline Selesai", value=row.get('deadline_penyelesaian','-'), disabled=True, key=f"dl_{row['id']}")
                d4.text_input("🔗 Referensi User", value=row.get('output_link_drive') or '-', disabled=True, key=f"ref_{row['id']}")

                st.text_area("📌 Catatan / Instruksi Khusus", value=row.get('notes') or '-', disabled=True, height=70, key=f"nt_{row['id']}")

                st.markdown("<div style='margin-top:25px;'></div>", unsafe_allow_html=True)
                st.markdown("<p style='font-weight: 800; color: #1e3a8a; font-size: 11px; margin-bottom:10px; text-transform: uppercase;'>🚀 Hasil Dokumentasi (Input Admin)</p>", unsafe_allow_html=True)
                
                if is_rejected:
                    rejection_reason = row.get('rejection_reason', 'Tidak ada keterangan')
                    st.error(f"🚫 Pengajuan ini telah ditolak. Data dikunci.\n\n**Alasan Penolakan:** {rejection_reason}")
                else:
                    with st.form(f"form_link_admin_{row['id']}"):
                        l1, l2, l3 = st.columns(3)
                        h_drive = l1.text_input("📁 Link Folder Drive", value=row.get('hasil_link_drive') or row.get('hasil_link_1') or '', placeholder="https://drive...")
                        h_video = l2.text_input("🎬 Link Video", value=row.get('hasil_video') or row.get('hasil_link_3') or '', placeholder="https://...")
                        h_flyer = l3.text_input("🖼️ Link Flyer", value=row.get('hasil_flyer') or row.get('hasil_link_2') or '', placeholder="https://...")
                        
                        can_update = row['status'].lower() in ['approved', 'done']
                        if st.form_submit_button("💾 SIMPAN DAN UPDATE LINK HASIL", use_container_width=True, disabled=not can_update):
                            with engine.begin() as conn:
                                conn.execute(text("""
                                    UPDATE pengajuan_dokumentasi SET 
                                    hasil_link_drive=:hdrive, hasil_video=:hvideo, hasil_flyer=:hflyer,
                                    hasil_link_1=:h1, hasil_link_2=:h2, hasil_link_3=:h3,
                                    updated_at=:now WHERE id=:id
                                """), {
                                    "hdrive": h_drive, "hvideo": h_video, "hflyer": h_flyer,
                                    "h1": h_drive, "h2": h_flyer, "h3": h_video,
                                    "now": datetime.now(), "id": row['id']
                                })
                            st.toast("✅ Link berhasil diperbarui dan terkirim ke User!"); time.sleep(0.5); st.rerun()

                st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
                a1, a2, a3, a4 = st.columns(4)
                
                if row['status'].lower() == 'pending':
                    if a1.button("✅ SETUJUI", key=f"btn_acc_{row['id']}", use_container_width=True):
                        with engine.begin() as conn:
                            conn.execute(text("UPDATE pengajuan_dokumentasi SET status='approved' WHERE id=:id"), {"id": row['id']})
                        st.rerun()
                    if a2.button("❌ TOLAK", key=f"btn_rej_{row['id']}", use_container_width=True):
                        st.session_state[f"show_reject_modal_{row['id']}"] = True
                    
                    if st.session_state.get(f"show_reject_modal_{row['id']}", False):
                        with st.form(f"form_reject_{row['id']}"):
                            st.warning("⚠️ Anda akan menolak pengajuan ini")
                            reject_reason = st.text_area("Alasan Penolakan", placeholder="Contoh: Data tidak lengkap, atau silahkan revisi...", key=f"reason_{row['id']}")
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.form_submit_button("✅ Konfirmasi Tolak", use_container_width=True, key=f"confirm_reject_{row['id']}"):
                                    with engine.begin() as conn:
                                        conn.execute(text("UPDATE pengajuan_dokumentasi SET status='rejected', rejection_reason=:rr WHERE id=:id"), {"id": row['id'], "rr": reject_reason})
                                    st.session_state[f"show_reject_modal_{row['id']}"] = False
                                    st.rerun()
                            with c2:
                                if st.form_submit_button("❌ Batal", use_container_width=True, key=f"cancel_reject_{row['id']}"):
                                    st.session_state[f"show_reject_modal_{row['id']}"] = False
                                    st.rerun()
                
                elif row['status'].lower() == 'approved':
                    if a1.button("🏁 SELESAIKAN", key=f"btn_done_{row['id']}", use_container_width=True, type="primary"):
                        with engine.begin() as conn:
                            conn.execute(text("UPDATE pengajuan_dokumentasi SET status='done' WHERE id=:id"), {"id": row['id']})
                        st.rerun()

                if a4.button("🗑️ HAPUS", key=f"btn_del_{row['id']}", use_container_width=True, type="secondary"):
                    st.session_state[f"confirm_delete_{row['id']}"] = True
                
                if st.session_state.get(f"confirm_delete_{row['id']}", False):
                    st.warning(f"⚠️ Yakin ingin menghapus pengajuan '{row['nama_pengaju']}'?")
                    col_confirm, col_cancel = st.columns(2)
                    with col_confirm:
                        if st.button("✅ Ya, Hapus", key=f"confirm_del_{row['id']}", use_container_width=True):
                            with engine.begin() as conn:
                                conn.execute(text("DELETE FROM pengajuan_dokumentasi WHERE id=:id"), {"id": row['id']})
                                conn.execute(text("DELETE FROM dokumentasi_calendar WHERE pengajuan_id=:id"), {"id": row['id']})
                            st.toast(f"✅ Pengajuan '{row['nama_pengaju']}' berhasil dihapus", icon="✅")
                            st.session_state[f"confirm_delete_{row['id']}"] = False
                            time.sleep(0.5)
                            st.rerun()
                    with col_cancel:
                        if st.button("❌ Batal", key=f"cancel_del_{row['id']}", use_container_width=True):
                            st.session_state[f"confirm_delete_{row['id']}"] = False
                            st.rerun()

            st.markdown("<div style='margin-bottom:20px;'></div>", unsafe_allow_html=True)

    # -----------------------------
    # PAGE 5: KALENDER DOKUMENTASI 
    # -----------------------------
    elif nav == "Kalender Dokumentasi":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>📅 Kalender Dokumentasi</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Visualisasi Jadwal Dokumentasi Korporat</p>
            </div>
        """, unsafe_allow_html=True)

        df_peng = pd.read_sql(text("""
            SELECT id as pengajuan_id, tanggal_acara as tanggal, nama_pengaju as nama_kegiatan, 
                   unit, status, created_at, jam_mulai, jam_selesai, nomor_telpon, 
                   hasil_link_drive, hasil_video, hasil_flyer
            FROM pengajuan_dokumentasi 
            ORDER BY tanggal_acara ASC
        """), engine)

        if df_peng.empty:
            combined_events = pd.DataFrame(columns=['pengajuan_id', 'tanggal', 'nama_kegiatan', 'unit', 'status', 'created_at', 'jam_mulai', 'jam_selesai', 'nomor_telpon', 'hasil_link_drive', 'hasil_video', 'hasil_flyer'])
        else:
            combined_events = df_peng.copy()
        
        try:
            df_cal = pd.read_sql(text("""
                SELECT pengajuan_id, doc_link FROM dokumentasi_calendar 
                WHERE doc_link IS NOT NULL AND doc_link != ''
            """), engine)
            if not df_cal.empty:
                for _, cal_row in df_cal.iterrows():
                    mask = combined_events['pengajuan_id'] == cal_row['pengajuan_id']
                    if mask.any():
                        combined_events.loc[mask, 'doc_link'] = cal_row['doc_link']
        except:
            pass

        with st.container(border=True):
            c_s1, c_s2, c_s3 = st.columns([1.2, 1.2, 1])
            with c_s1:
                st.markdown("<p style='font-size:0.85rem; margin-bottom:8px; font-weight:700; color:#475569;'>PILIH BULAN</p>", unsafe_allow_html=True)
                sel_m = st.selectbox("Bulan", list(range(1,13)), format_func=lambda x: calendar.month_name[x], index=datetime.now().month-1, key="admin_cal_month", label_visibility="collapsed")
            with c_s2:
                st.markdown("<p style='font-size:0.85rem; margin-bottom:8px; font-weight:700; color:#475569;'>PILIH TAHUN</p>", unsafe_allow_html=True)
                sel_y = st.number_input("Tahun", value=datetime.now().year, key="admin_cal_year", label_visibility="collapsed")
            with c_s3:
                st.markdown("<p style='font-size:0.85rem; margin-bottom:8px; font-weight:700; color:#475569;'>STATUS</p>", unsafe_allow_html=True)
                sel_status = st.selectbox("Status", ["Semua", "Approved", "Done", "Pending"], key="admin_cal_status", label_visibility="collapsed")
            
            if not combined_events.empty:
                combined_events['date_obj'] = combined_events['tanggal'].apply(parse_date_str)
                status_filter = combined_events['status'].fillna('').str.lower()
                
                if sel_status == "Semua":
                    status_list = ['approved', 'done', 'pending', '']
                else:
                    status_list = [sel_status.lower()]
                
                combined_events_filtered = combined_events[
                    status_filter.isin(status_list)
                ]
            else:
                combined_events_filtered = combined_events
            
            st.markdown(render_month_calendar(sel_y, sel_m, combined_events_filtered.to_dict('records')), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        
        col_add_man, col_list_man = st.columns([1.2, 1.8])

        with col_add_man:
            with st.container(border=True):
                st.markdown("<p style='font-weight: 800; color: #1e3a8a; font-size: 15px;'>➕ TAMBAH AGENDA MANUAL</p>", unsafe_allow_html=True)
                with st.form("form_manual_admin"):
                    m_tgl = st.date_input("Tanggal")
                    m_nama = st.text_input("Nama Kegiatan")
                    m_unit = st.text_input("Unit/Lokasi")
                    m_jm = st.time_input("Jam Mulai")
                    m_js = st.time_input("Jam Selesai")
                    if st.form_submit_button("🚀 Masukkan Agenda", use_container_width=True):
                        if m_nama:
                            with engine.begin() as conn:
                                res = conn.execute(text("""INSERT INTO pengajuan_dokumentasi 
                                    (nama_pengaju, unit, tanggal_acara, jam_mulai, jam_selesai, status, created_at) 
                                    VALUES (:n, :u, :t, :jm, :js, 'approved', :ca) RETURNING id"""),
                                    {"n": m_nama, "u": m_unit, "t": m_tgl.strftime("%d/%m/%Y"), 
                                    "jm": m_jm.strftime("%H:%M"), "js": m_js.strftime("%H:%M"), "ca": datetime.now()})
                                new_id = res.fetchone()[0]
                                
                                conn.execute(text("INSERT INTO dokumentasi_calendar (pengajuan_id, tanggal, nama_kegiatan, unit, status) VALUES (:id, :t, :n, :u, 'approved')"),
                                            {"id": new_id, "t": m_tgl.strftime("%d/%m/%Y"), "n": m_nama, "u": m_unit})
                            st.rerun()

        with col_list_man:
                    with st.container(border=True):
                        st.markdown("<p style='font-weight: 800; color: #1e3a8a; font-size: 15px;'>📋 DAFTAR AGENDA AKTIF</p>", unsafe_allow_html=True)
                        
                        if combined_events.empty:
                            st.caption("Belum ada jadwal.")
                        else:
                            st.markdown("<p style='font-size:0.75rem; margin-bottom:8px; margin-top:15px; font-weight:700; color:#475569;'>🔍 FILTER JADWAL</p>", unsafe_allow_html=True)
                            
                            f_col1, f_col2, f_col3 = st.columns([1.5, 1, 1.2])
                            
                            with f_col1:
                                st.markdown("<p style='font-size:0.7rem; margin-bottom:4px; font-weight:700; color:#64748b;'>BULAN</p>", unsafe_allow_html=True)
                                month_options = [(0, "Semua Bulan")] + [(i, calendar.month_name[i]) for i in range(1, 13)]
                                filter_month = st.selectbox(
                                    "Bulan",
                                    options=[opt[0] for opt in month_options],
                                    format_func=lambda x: next(opt[1] for opt in month_options if opt[0] == x),
                                    index=datetime.now().month, 
                                    key="admin_agenda_month",
                                    label_visibility="collapsed"
                                )
                            
                            with f_col2:
                                st.markdown("<p style='font-size:0.7rem; margin-bottom:4px; font-weight:700; color:#64748b;'>TAHUN</p>", unsafe_allow_html=True)
                                filter_year = st.number_input("Tahun", value=datetime.now().year, key="admin_agenda_year", label_visibility="collapsed")
                            
                            with f_col3:
                                st.markdown("<p style='font-size:0.7rem; margin-bottom:4px; font-weight:700; color:#64748b;'>PILIH HARI</p>", unsafe_allow_html=True)
                                mode_hari = st.selectbox("Mode", ["Semua Hari", "Tanggal Spesifik"], key="mode_hari", label_visibility="collapsed")
                                
                                if mode_hari == "Tanggal Spesifik":
                                    filter_date_list = st.date_input("Pilih Tanggal", value=datetime.now().date(), key="admin_agenda_date", label_visibility="collapsed")

                            combined_events['date_obj'] = combined_events['tanggal'].apply(parse_date_str)
                            
                            mask = (combined_events['date_obj'].apply(lambda x: x.year if x else 0) == filter_year)
                            
                            if filter_month != 0:
                                mask &= (combined_events['date_obj'].apply(lambda x: x.month if x else 0) == filter_month)
                            
                            if mode_hari == "Tanggal Spesifik":
                                mask &= (combined_events['date_obj'] == filter_date_list)
                            
                            df_cal_filtered = combined_events[mask]

                            st.markdown("<div style='margin-top:15px; border-top: 1px solid #f1f5f9; padding-top:10px;'></div>", unsafe_allow_html=True)
                            
                            if df_cal_filtered.empty:
                                st.warning("Tidak ada jadwal untuk periode ini.")
                            else:
                                for _, cal_row in df_cal_filtered.iterrows():
                                    drive_link = cal_row.get('hasil_link_drive')
                                    video_link = cal_row.get('hasil_video')
                                    flyer_link = cal_row.get('hasil_flyer')
                                    
                                    jam_mulai = cal_row.get('jam_mulai') or "-"
                                    jam_selesai = cal_row.get('jam_selesai') or "-"
                                    
                                    st_val = str(cal_row['status']).lower()
                                    colors = {
                                        'approved': ('#10b981', '#f0fdf4'),
                                        'pending': ('#f59e0b', '#fff7ed'),
                                        'done': ('#6366f1', '#eef2ff'),
                                        '': ('#10b981', '#f0fdf4')
                                    }
                                    accent, bg = colors.get(st_val, ('#64748b', '#f8fafc'))
                                    
                                    doc_link_section = render_documentation_links(drive_link, video_link, flyer_link)
                                    
                                    st.markdown(f"""
                                        <div style='background: white; padding: 20px; border-radius: 16px; border-left: 8px solid {accent}; margin-bottom: 15px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); display: flex; justify-content: space-between; align-items: flex-start;'>
                                            <div style='flex: 3;'>
                                                <div style='display: flex; align-items: center; gap: 15px; margin-bottom: 8px;'>
                                                    <div style='background: #1e3a8a; color: white; padding: 4px 12px; border-radius: 8px; font-weight: 700; font-size: 0.85rem;'>
                                                        {cal_row['date_obj'].strftime('%d %b %Y')}
                                                    </div>
                                                    <div style='color: #64748b; font-weight: 600; font-size: 0.9rem;'>
                                                        🕒 {jam_mulai} - {jam_selesai}
                                                    </div>
                                                </div>
                                                <div style='font-size: 1.2rem; font-weight: 800; color: #0f172a;'>{cal_row['nama_kegiatan']}</div>
                                                <div style='margin-top: 4px; color: #475569; font-size: 0.9rem;'>📍 Unit: <span style='font-weight: 600; color: #1e3a8a;'>{cal_row.get('unit','')}</span></div>
                                                {doc_link_section}
                                            </div>
                                            <div style='flex: 1; text-align: right;'>
                                                <span style='background: {bg}; color: {accent}; padding: 8px 16px; border-radius: 12px; font-size: 0.75rem; font-weight: 800; border: 1.5px solid {accent}40; text-transform: uppercase;'>
                                                    {cal_row.get('status') or 'APPROVED'}
                                                </span>
                                            </div>
                                        </div>
                                    """, unsafe_allow_html=True)
                                    
                                    col1, col2 = st.columns([1, 3])
                                    with col1:
                                        if st.button("🗑️ Hapus Kegiatan", key=f"del_admin_agenda_{cal_row['pengajuan_id']}", 
                                                   help="Hapus agenda ini dari kalender", type="secondary"):
                                            st.session_state[f"confirm_delete_{cal_row['pengajuan_id']}"] = True
                                    
                                    if st.session_state.get(f"confirm_delete_{cal_row['pengajuan_id']}", False):
                                        st.markdown(f"<div style='background: #fef2f2; border-left: 4px solid #ef4444; padding: 16px; border-radius: 8px; margin-bottom: 12px;'><p style='color: #991b1b; margin: 0; font-weight: 700;'>⚠️ Konfirmasi Penghapusan</p><p style='color: #7f1d1d; margin: 8px 0 0 0; font-size: 0.95rem;'>Yakin ingin menghapus kegiatan <strong>'{cal_row['nama_kegiatan']}'</strong>?</p></div>", unsafe_allow_html=True)
                                        col_confirm, col_cancel = st.columns(2, gap="small")
                                        with col_confirm:
                                            if st.button("✅ Ya, Hapus", key=f"confirm_{cal_row['pengajuan_id']}", use_container_width=True, type="primary"):
                                                with engine.begin() as conn:
                                                    pengajuan_id = cal_row.get('pengajuan_id')
                                                    if pengajuan_id and pd.notna(pengajuan_id):
                                                        conn.execute(text("DELETE FROM pengajuan_dokumentasi WHERE id=:pid"), {"pid": int(pengajuan_id)})
                                                        conn.execute(text("DELETE FROM dokumentasi_calendar WHERE pengajuan_id=:pid"), {"pid": int(pengajuan_id)})
                                                st.toast(f"✅ Agenda '{cal_row['nama_kegiatan']}' berhasil dihapus", icon="✅")
                                                st.session_state[f"confirm_delete_{cal_row['pengajuan_id']}"] = False
                                                time.sleep(0.5)
                                                st.rerun()
                                        with col_cancel:
                                            if st.button("❌ Batal", key=f"cancel_{cal_row['pengajuan_id']}", use_container_width=True, type="secondary"):
                                                st.session_state[f"confirm_delete_{cal_row['pengajuan_id']}"] = False
                                                st.rerun()
 
    # --------------------------
    # PAGE 6: PENGATURAN UNIT
    # -------------------------
    elif nav == "Pengaturan Unit":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>⚙️ Pengaturan Unit</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Kelola Database Unit Kerja & Akun Monitoring</p>
            </div>
        """, unsafe_allow_html=True)

        col_add, col_list = st.columns([1, 1.5])

        with col_add:
            with st.container(border=True):
                st.markdown("<h4 style='color: #1e3a8a; margin-top:0;'>➕ Daftarkan Unit</h4>", unsafe_allow_html=True)
                un = st.text_input("Nama Unit", placeholder="Contoh: UP3 Tanjung Karang")
                ig = st.text_input("Username IG", placeholder="@username_unit")
                if st.button("Simpan Unit", use_container_width=True, type="primary"):
                    if un and ig:
                        try:
                            username = extract_username(ig)
                            with engine.begin() as conn:
                                existing = conn.execute(text("SELECT id FROM daftar_akun_unit WHERE username_ig = :u"), {"u": username}).fetchone()
                                if existing:
                                    conn.execute(text("UPDATE daftar_akun_unit SET nama_unit = :n WHERE username_ig = :u"), {"n": un, "u": username})
                                    st.info(f"Unit '{un}' sudah ada, data diperbarui!")
                                else:
                                    conn.execute(text("INSERT INTO daftar_akun_unit (nama_unit, username_ig) VALUES (:n, :u)"),
                                            {"n": un, "u": username})
                                    st.toast("Unit berhasil didaftarkan!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Gagal menyimpan unit: {e}")

        with col_list:
            with st.container(border=True):
                st.markdown("<h4 style='color: #1e3a8a; margin-top:0;'>📋 Daftar Unit Aktif</h4>", unsafe_allow_html=True)
                ud = pd.read_sql(text("SELECT * FROM daftar_akun_unit"), engine)
                if ud.empty:
                    st.info("Belum ada unit terdaftar.")
                else:
                    st.dataframe(ud, use_container_width=True, hide_index=True)
                    st.markdown("---")
                    target = st.selectbox("Pilih unit untuk dihapus:", ud['username_ig'].tolist())
                    
                    if st.button("Hapus Unit", use_container_width=True, type="secondary"):
                        st.session_state[f"confirm_delete_unit_{target}"] = True
                    
                    if st.session_state.get(f"confirm_delete_unit_{target}", False):
                        unit_name = ud[ud['username_ig'] == target]['nama_unit'].values[0]
                        st.warning(f"⚠️ Yakin ingin menghapus unit '{unit_name}' dan semua data rekapitulasinya?")
                        col_confirm, col_cancel = st.columns(2)
                        with col_confirm:
                            if st.button("✅ Ya, Hapus Unit", key=f"confirm_del_unit_{target}", use_container_width=True):
                                try:
                                    with engine.begin() as conn:
                                        conn.execute(text("DELETE FROM monitoring_pln WHERE pic_unit = :un"), {"un": unit_name})
                                        conn.execute(text("DELETE FROM daftar_akun_unit WHERE username_ig = :u"), {"u": target})
                                    st.toast(f"✅ Unit {unit_name} dan semua data rekapitulasinya berhasil dihapus", icon="✅")
                                    st.session_state[f"confirm_delete_unit_{target}"] = False
                                    time.sleep(0.5)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Gagal menghapus unit: {e}")
                        with col_cancel:
                            if st.button("❌ Batal", key=f"cancel_del_unit_{target}", use_container_width=True):
                                st.session_state[f"confirm_delete_unit_{target}"] = False
                                st.rerun()

    # -------------------------
    # PAGE 7: MANAJEMEN USER
    # -------------------------
    elif nav == "Manajemen User":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>👥 Manajemen Pengguna</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Kelola Akses Akun, Role, dan Otoritas Unit Kerja</p>
            </div>
        """, unsafe_allow_html=True)

        tab_view, tab_add, tab_edit, tab_reset = st.tabs([
            "👁️ Lihat User", "➕ Tambah User", "✏️ Edit/Hapus User", "🔐 Reset Password"
        ])

        # --- TAB 1: LIHAT USER ---
        with tab_view:
            st.markdown("<h4 style='color: #1e3a8a;'>📋 Daftar Seluruh Pengguna</h4>", unsafe_allow_html=True)
            try:
                df_users = pd.read_sql(text("SELECT id, username, role, unit, created_at FROM users ORDER BY created_at DESC"), engine)
                if not df_users.empty:
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("Total User", len(df_users))
                    with c2:
                        st.metric("Admin", len(df_users[df_users['role'] == 'admin']))
                    with c3:
                        st.metric("User Biasa", len(df_users[df_users['role'] == 'user']))
                    
                    st.write("")
                    st.dataframe(df_users, use_container_width=True, hide_index=True)
                else:
                    st.info("ℹ️ Belum ada user terdaftar dalam database.")
            except Exception as e:
                st.error(f"❌ Error mengambil data: {e}")

        # --- TAB 2: TAMBAH USER ---
        with tab_add:
            col_form, col_hint = st.columns([1.2, 0.8])
            with col_form:
                with st.container(border=True):
                    st.markdown("<h4 style='color: #1e3a8a; margin-top:0;'>➕ Registrasi User Baru</h4>", unsafe_allow_html=True)
                    with st.form("form_add_user", clear_on_submit=True):
                        new_username = st.text_input("Username", placeholder="Masukkan username unik")
                        p1, p2 = st.columns(2)
                        new_password = p1.text_input("Password", type="password", help="Minimal 6 karakter")
                        new_password_conf = p2.text_input("Konfirmasi Password", type="password")
                        
                        r1, r2 = st.columns(2)
                        new_role = r1.selectbox("Role Akses", ["user", "admin"])
                        new_unit = r2.text_input("Unit Kerja", placeholder="Misal: UP3 Lampung")
                        
                        st.write("")
                        if st.form_submit_button("🚀 Daftarkan User Baru", use_container_width=True, type="primary"):
                            if not new_username or len(new_username) < 3:
                                st.error("❌ Username minimal 3 karakter")
                            elif new_password != new_password_conf:
                                st.error("❌ Password tidak cocok")
                            elif len(new_password) < 6:
                                st.error("❌ Password minimal 6 karakter")
                            else:
                                try:
                                    if register_user(new_username, new_password, new_role, new_unit):
                                        st.success(f"✅ User '{new_username}' berhasil ditambahkan!")
                                        st.rerun()
                                    else:
                                        st.error("❌ Username sudah terdaftar")
                                except Exception as e:
                                    st.error(f"❌ Gagal membuat user: {e}")
            with col_hint:
                st.info("""
                **Tips Keamanan Akun:**
                1. Gunakan Username tanpa spasi.
                2. Password minimal mengandung 6 karakter.
                3. Pastikan Unit Kerja diisi sesuai wilayah tugas user tersebut.
                """)

        # --- TAB 3: EDIT & HAPUS USER (VERSI BARU - TANPA EXPANDER) ---
        with tab_edit:
            st.markdown("<h4 style='color: #1e3a8a;'>✏️ Modifikasi & Eliminasi Akun</h4>", unsafe_allow_html=True)
            
            df_edit = pd.read_sql(text("SELECT * FROM users ORDER BY username"), engine)
            
            if not df_edit.empty:
                selected_user = st.selectbox("🎯 Pilih Target User", df_edit['username'].tolist(), key="sel_edit")
                user_data = df_edit[df_edit['username'] == selected_user].iloc[0]
                
                st.session_state['current_edit_user_id'] = int(user_data['id'])
                
                col_left, col_right = st.columns([1.5, 1])
                
                with col_left:
                    with st.container(border=True):
                        st.markdown("<p style='font-weight: 700; color: #1e3a8a;'>📝 Update Informasi</p>", unsafe_allow_html=True)
                        
                        up_role = st.selectbox("Role Baru", ["user", "admin"], 
                                            index=0 if user_data['role'] == 'user' else 1, key="up_role_select")
                        up_unit = st.text_input("Unit Kerja Baru", value=str(user_data.get('unit', '')), key="up_unit_input")
                        
                        if st.button("💾 Simpan Perubahan", use_container_width=True, type="primary", key="btn_save_edit"):
                            try:
                                with engine.begin() as conn:
                                    conn.execute(text("UPDATE users SET role=:r, unit=:u WHERE id=:id"), 
                                            {"r": up_role, "u": up_unit, "id": int(user_data['id'])})
                                st.success(f"✅ Berhasil update {selected_user}")
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Gagal update user: {e}")

                with col_right:
                    with st.container(border=True):
                        st.markdown("<p style='font-weight: 700; color: #ef4444;'>⚠️ Hapus Akun</p>", unsafe_allow_html=True)
                        st.write(f"Menghapus `{selected_user}` bersifat permanen.")
                        
                        if st.button("🗑️ Hapus User", use_container_width=True, type="secondary", key="btn_delete_user"):
                            st.session_state[f"confirm_delete_user_{selected_user}"] = True
                        
                        if st.session_state.get(f"confirm_delete_user_{selected_user}", False):
                            st.warning(f"⚠️ Yakin ingin menghapus user '{selected_user}'? Tindakan ini tidak bisa dibatalkan.")
                            col_confirm, col_cancel = st.columns(2)
                            with col_confirm:
                                if st.button("✅ Ya, Hapus User", key=f"confirm_delete_ok_{selected_user}", use_container_width=True):
                                    try:
                                        user_id = int(user_data['id'])
                                        with engine.begin() as conn:
                                            conn.execute(text("""
                                                DELETE FROM dokumentasi_calendar 
                                                WHERE pengajuan_id IN (SELECT id FROM pengajuan_dokumentasi WHERE user_id = :uid)
                                            """), {"uid": user_id})
                                            conn.execute(text("DELETE FROM pengajuan_dokumentasi WHERE user_id = :uid"), {"uid": user_id})
                                            conn.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
                                        
                                        with engine.begin() as verify_conn:
                                            verify_result = verify_conn.execute(text("SELECT COUNT(1) FROM users WHERE id=:id"), {"id": user_id}).fetchone()
                                        
                                        if not verify_result or verify_result[0] == 0:
                                            st.toast(f"✅ User '{selected_user}' dan semua dokumentasi terkaitnya telah dihapus.", icon="✅")
                                            
                                            if st.session_state.get('user', {}).get('id') == user_id:
                                                st.session_state['user'] = None
                                            
                                            st.session_state[f"confirm_delete_user_{selected_user}"] = False
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.error(f"❌ Gagal menghapus {selected_user}: masih ada di database.")
                                    except Exception as e:
                                        st.error(f"❌ Gagal menghapus user: {str(e)}")
                            with col_cancel:
                                if st.button("❌ Batal", key=f"cancel_delete_{selected_user}", use_container_width=True):
                                    st.session_state[f"confirm_delete_user_{selected_user}"] = False
                                    st.rerun()
            else:
                st.info("Data user kosong.")

        with tab_reset:
            st.markdown("<h4 style='color: #1e3a8a;'>🔐 Reset Password</h4>", unsafe_allow_html=True)
            
            with st.container(border=True):
                df_res = pd.read_sql(text("SELECT username FROM users"), engine)
                target_res = st.selectbox("Pilih Akun", df_res['username'].tolist(), key="res_box")
                new_pwd_res = st.text_input("Password Baru", type="password", key="res_input")
                
                st.write("")
                if st.button("🔑 Setel Ulang Password", type="primary", use_container_width=True):
                    if len(new_pwd_res) >= 6:
                        hashed_pwd = verify_password(new_pwd_res) 
                        with engine.begin() as conn:
                            conn.execute(text("UPDATE users SET password=:p WHERE username=:u"), 
                                    {"p": hashed_pwd, "u": target_res})
                        st.success(f"✅ Password {target_res} sekarang telah berubah!")
                    else:
                        st.error("❌ Password minimal 6 karakter!")

    # ---------------------------
    # PAGE 8: PENGATURAN ADMIN
    # ---------------------------
    elif nav == "Pengaturan Admin":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>🔐 Pengaturan Keamanan</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Kelola Password dan Informasi Akun Administrator</p>
            </div>
        """, unsafe_allow_html=True)

        col_pwd, col_info = st.columns([1.4, 1])

        with col_pwd:
            with st.container(border=True):
                st.markdown("<h4 style='color: #1e3a8a; margin-top:0;'>🔑 Ubah Password</h4>", unsafe_allow_html=True)
                
                with st.form("form_change_pwd", clear_on_submit=True):
                    old_pass = st.text_input("Password Lama", type="password", placeholder="Masukkan password saat ini")
                    st.markdown("<hr style='margin: 10px 0; border: 0; border-top: 1px solid #eee;'>", unsafe_allow_html=True)
                    new_pass = st.text_input("Password Baru", type="password", help="Minimal 6 karakter", placeholder="Masukkan password baru")
                    new_pass_conf = st.text_input("Konfirmasi Password Baru", type="password", placeholder="Ulangi password baru")
                    
                    st.write("")
                    submit_pwd = st.form_submit_button("🔐 Update Password Sekarang", use_container_width=True, type="primary")
                    
                    if submit_pwd:
                        try:
                            if not old_pass or not new_pass or not new_pass_conf:
                                st.error("❌ Semua field harus diisi")
                            elif len(new_pass) < 6:
                                st.error("❌ Password baru minimal 6 karakter")
                            elif new_pass != new_pass_conf:
                                st.error("❌ Konfirmasi password tidak cocok")
                            else:
                                admin_id = st.session_state.user['id']
                                admin_username = st.session_state.user['username']
                                old_pass_hash = verify_password(old_pass)
                                
                                check = pd.read_sql(
                                    text("SELECT id FROM users WHERE username=:u AND password=:p"), 
                                    engine, 
                                    params={"u": admin_username, "p": old_pass_hash}
                                )
                                
                                if check.empty:
                                    st.error("❌ Password lama tidak sesuai")
                                else:
                                    new_pass_hash = verify_password(new_pass)
                                    if update_password_direct(admin_id, new_pass_hash):
                                        st.success("✅ Password berhasil diubah!")
                                        st.toast("Sesi berakhir, silakan login ulang", icon="⏳")
                                        import time
                                        time.sleep(1.5)
                                        del st.session_state.user
                                        st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")

        with col_info:
            with st.container(border=True):
                st.markdown("<h4 style='color: #1e3a8a; margin-top:0;'>ℹ️ Profil Admin</h4>", unsafe_allow_html=True)
                admin_user = st.session_state.user
                
                st.markdown(f"""
                    <div style='background-color: #f0f7ff; padding: 20px; border-radius: 15px; border: 1px solid #dbeafe;'>
                        <div style='margin-bottom: 15px;'>
                            <label style='color: #64748b; font-size: 12px; font-weight: 600; text-transform: uppercase;'>Username</label>
                            <div style='color: #1e3a8a; font-weight: 700; font-size: 16px;'>{admin_user['username']}</div>
                        </div>
                        <div style='margin-bottom: 15px;'>
                            <label style='color: #64748b; font-size: 12px; font-weight: 600; text-transform: uppercase;'>Role Akses</label>
                            <div style='color: #1e3a8a; font-weight: 700; font-size: 16px;'>{admin_user['role'].upper()}</div>
                        </div>
                        <div style='margin-bottom: 15px;'>
                            <label style='color: #64748b; font-size: 12px; font-weight: 600; text-transform: uppercase;'>Unit Kerja</label>
                            <div style='color: #1e3a8a; font-weight: 700; font-size: 16px;'>{admin_user['unit']}</div>
                        </div>
                        <div>
                            <label style='color: #64748b; font-size: 12px; font-weight: 600; text-transform: uppercase;'>Waktu Login</label>
                            <div style='color: #1e3a8a; font-weight: 700; font-size: 14px;'>{datetime.now().strftime('%d %b %Y, %H:%M')}</div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
                
                st.write("")
                st.info("Gunakan menu ini untuk memastikan akun Anda tetap aman. Jangan berikan password kepada siapapun.")
                
# ===========
# ROLE USER
# ===========
else:  # role: user
     
    # ---------------------------
    # PAGE 1: DASHBOARD USER
    # ---------------------------
    if nav == "Dashboard User":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>📊 Dashboard Overview</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Pantau progres pengajuan dokumentasi Anda dalam satu layar.</p>
            </div>
        """, unsafe_allow_html=True)       
        user_id = st.session_state.user['id']
        df_user = pd.read_sql(text("SELECT * FROM pengajuan_dokumentasi WHERE user_id = :uid ORDER BY created_at DESC"), 
                                engine, params={"uid": user_id})
        
        if not df_user.empty:
            df_user['status'] = df_user['status'].fillna('pending').str.lower()
            valid_statuses = ['pending', 'approved', 'done', 'rejected']
            df_user['status'] = df_user['status'].apply(lambda x: x if x in valid_statuses else 'pending')
        
        with st.container(border=True):
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("📝 Total Pengajuan", f"{len(df_user)}")
            m2.metric("⏳ Status Pending", len(df_user[df_user['status'] == 'pending']))
            m3.metric("🚀 Status Approved", len(df_user[df_user['status'] == 'approved']))
            m4.metric("✅ Status Selesai", len(df_user[df_user['status'] == 'done']))
            m5.metric("❌ Status Ditolak", len(df_user[df_user['status'] == 'rejected']))

        st.markdown("<div style='margin-top:30px;'></div>", unsafe_allow_html=True)

        col_table, col_stat = st.columns([1.8, 1], gap="medium")

        with col_table:
            st.markdown("<h4 style='margin-bottom:15px; font-weight:800; color:#1e293b;'>📌 5 Pengajuan Terakhir</h4>", unsafe_allow_html=True)
            if not df_user.empty:
                df_recent = df_user.sort_values('created_at', ascending=False).head(5).copy()
                
                status_display = {
                    "pending": "⏳ Pending Review",
                    "approved": "🔵 In Progress",
                    "done": "✅ Finished",
                    "rejected": "❌ Rejected"
                }
                df_recent['status'] = df_recent['status'].map(status_display)

                st.dataframe(
                    df_recent[['tanggal_acara', 'nama_pengaju', 'status']],
                    column_config={
                        "status": st.column_config.TextColumn("Status Progress", width="medium"),
                        "tanggal_acara": "📅 Tanggal Acara",
                        "nama_pengaju": "📝 Nama Kegiatan"
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Belum ada data pengajuan.")

        with col_stat:
            st.markdown("<h4 style='margin-bottom:15px; font-weight:800; color:#1e293b;'>📊 Ringkasan Status</h4>", unsafe_allow_html=True)
            with st.container(border=True):
                if not df_user.empty:
                    total = len(df_user)
                    
                    for label, key in [("Selesai", "done"), ("Diproses", "approved"), ("Menunggu", "pending"), ("Ditolak", "rejected")]:
                        count = len(df_user[df_user['status'] == key])
                        pct = (count/total) if total > 0 else 0
                        st.markdown(f"<div style='display:flex; justify-content:space-between; font-size:0.85rem;'><span><b>{label}</b></span><span>{count} Data</span></div>", unsafe_allow_html=True)
                        st.progress(pct)
                        st.markdown("<div style='margin-bottom:8px;'></div>", unsafe_allow_html=True)
                else:
                    st.write("Data belum tersedia.")
                    
    # ---------------------------------
    # PAGE 2: KALENDER DOKUMENTASI 
    # --------------------------------
    elif nav == "Kalender Dokumentasi":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 35px; border-radius: 25px; margin-bottom: 30px; box-shadow: 0 10px 20px rgba(14, 165, 233, 0.2);'>
                <h1 style='color: white; margin: 0; font-size: 32px; font-weight: 800; letter-spacing: -0.5px;'>📅 Kalender & Agenda Tim</h1>
                <p style='color: #e0f2fe; margin: 8px 0 0 0; opacity: 0.9; font-size: 16px;'>Pantau ketersediaan dokumentasi dan jadwal kegiatan secara real-time.</p>
            </div>
        """, unsafe_allow_html=True)

        user_id = st.session_state.user['id']

        with st.container():
            f1, f2, f3 = st.columns([1.2, 1, 1])
            with f1:
                st.markdown("<p style='font-size:0.85rem; margin-bottom:8px; font-weight:700; color:#475569;'>MODE TAMPILAN</p>", unsafe_allow_html=True)
                show_mine = st.toggle("Tampilkan Jadwal Saya Saja", value=False)
            with f2:
                s_month = st.selectbox("Bulan Visual", list(range(1,13)), format_func=lambda x: calendar.month_name[x], index=datetime.now().month-1)
            with f3:
                s_year = st.number_input("Tahun Visual", value=datetime.now().year)

        try:
            query = """
                SELECT c.*, p.jam_mulai, p.jam_selesai, p.user_id, COALESCE(p.status, '') as p_status,
                       p.hasil_link_drive, p.hasil_video, p.hasil_flyer
                FROM dokumentasi_calendar c
                LEFT JOIN pengajuan_dokumentasi p ON c.pengajuan_id = p.id
            """
            df_all = pd.read_sql(text(query + (" WHERE p.user_id = :uid" if show_mine else "")), engine, params={"uid": user_id} if show_mine else None)

            if not df_all.empty:
                df_all['p_status'] = df_all['p_status'].fillna('')
                df_all = df_all[df_all['p_status'].isin(['approved', 'done', ''])]
                df_all['date_obj'] = df_all['tanggal'].apply(parse_date_str)

            # --- RENDER KALENDER VISUAL ---
            st.markdown("<div style='margin-top:30px;'></div>", unsafe_allow_html=True)
            events_list = df_all.to_dict('records') if not df_all.empty else []
            st.markdown(render_month_calendar(s_year, s_month, events_list), unsafe_allow_html=True)

            # --- DAFTAR DETAIL KEGIATAN (SMART FILTER) ---
            st.markdown("<h3 style='color: #1e3a8a; font-size: 22px; font-weight: 800; margin-top: 40px; margin-bottom: 20px;'>📋 Daftar Detail Kegiatan</h3>", unsafe_allow_html=True)

            if not df_all.empty:
                with st.container(border=True):
                    search_query = st.text_input("🔍 Cari Nama Kegiatan...", placeholder="Ketik nama acara...")
                    
                    sf1, sf2, sf3, sf4 = st.columns([1, 1, 1, 1])
                    
                    with sf1:
                        st.markdown("<p style='font-size:0.75rem; margin-bottom:4px; font-weight:700; color:#475569;'>BULAN</p>", unsafe_allow_html=True)
                        filter_month = st.selectbox("Bulan", 
                                                    [0] + list(range(1,13)),
                                                    format_func=lambda x: "Tampilkan Semua" if x == 0 else calendar.month_name[x],
                                                    key="user_cal_filter_month", label_visibility="collapsed")
                    
                    with sf2:
                        st.markdown("<p style='font-size:0.75rem; margin-bottom:4px; font-weight:700; color:#475569;'>MODE HARI</p>", unsafe_allow_html=True)
                        mode_hari = st.selectbox("Mode", ["Semua Hari", "Pilih Tanggal"], key="mode_hari_user", label_visibility="collapsed")
                    
                    with sf3:
                        if mode_hari == "Pilih Tanggal":
                            st.markdown("<p style='font-size:0.75rem; margin-bottom:4px; font-weight:700; color:#475569;'>TANGGAL SPESIFIK</p>", unsafe_allow_html=True)
                            filter_date = st.date_input("Tanggal", value=datetime.now().date(), key="user_cal_filter_date", label_visibility="collapsed")
                        else:
                            st.markdown("<p style='font-size:0.75rem; margin-bottom:4px; font-weight:700; color:#475569;'>UNIT</p>", unsafe_allow_html=True)
                            unit_list = ["Semua Unit"] + sorted([u for u in df_all['unit'].unique().tolist() if pd.notna(u)])
                            sel_unit = st.selectbox("Unit", unit_list, key="user_cal_unit", label_visibility="collapsed")
                    
                    with sf4:
                        if mode_hari == "Pilih Tanggal":
                            st.markdown("<p style='font-size:0.75rem; margin-bottom:4px; font-weight:700; color:#475569;'>UNIT</p>", unsafe_allow_html=True)
                            unit_list = ["Semua Unit"] + sorted([u for u in df_all['unit'].unique().tolist() if pd.notna(u)])
                            sel_unit = st.selectbox("Unit_2", unit_list, key="user_cal_unit_2", label_visibility="collapsed")
                        else:
                            st.markdown("<p style='font-size:0.75rem; margin-bottom:4px; font-weight:700; color:#475569;'>TAHUN</p>", unsafe_allow_html=True)
                            sel_year = st.number_input("Tahun", value=datetime.now().year, key="user_cal_year", label_visibility="collapsed")

                df_table = df_all.copy()

                if mode_hari == "Semua Hari":
                    df_table = df_table[df_table['date_obj'].apply(lambda x: x.year if x else 0) == sel_year]

                if filter_month != 0:
                    df_table = df_table[df_table['date_obj'].apply(lambda x: x.month if x else 0) == filter_month]

                if mode_hari == "Pilih Tanggal":
                    df_table = df_table[df_table['date_obj'] == filter_date]

                if search_query:
                    df_table = df_table[df_table['nama_kegiatan'].str.contains(search_query, case=False, na=False)]
                
                if sel_unit != "Semua Unit":
                    df_table = df_table[df_table['unit'] == sel_unit]

                if not df_table.empty:
                    df_table = df_table.sort_values(by='date_obj')
                    for _, row in df_table.iterrows():
                        st_val = str(row['p_status']).lower()
                        colors = {
                            'approved': ('#10b981', '#f0fdf4'),
                            'pending': ('#f59e0b', '#fff7ed'),
                            'done': ('#6366f1', '#eef2ff'),
                            '': ('#10b981', '#f0fdf4')
                        }
                        accent, bg = colors.get(st_val, ('#64748b', '#f8fafc'))
                        
                        drive_link = row.get('hasil_link_drive')
                        video_link = row.get('hasil_video')
                        flyer_link = row.get('hasil_flyer')
                        
                        doc_link_section = render_documentation_links(drive_link, video_link, flyer_link)

                        st.markdown(f"""
                            <div style='background: white; padding: 20px; border-radius: 16px; border-left: 8px solid {accent}; margin-bottom: 15px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); display: flex; justify-content: space-between; align-items: flex-start;'>
                                <div style='flex: 3;'>
                                    <div style='display: flex; align-items: center; gap: 15px; margin-bottom: 8px;'>
                                        <div style='background: #1e3a8a; color: white; padding: 4px 12px; border-radius: 8px; font-weight: 700; font-size: 0.85rem;'>
                                            {row['date_obj'].strftime('%d %b %Y')}
                                        </div>
                                        <div style='color: #64748b; font-weight: 600; font-size: 0.9rem;'>
                                            🕒 {row.get('jam_mulai') or '08:00'} - {row.get('jam_selesai') or 'Selesai'}
                                        </div>
                                    </div>
                                    <div style='font-size: 1.2rem; font-weight: 800; color: #0f172a;'>{row['nama_kegiatan']}</div>
                                    <div style='margin-top: 4px; color: #475569; font-size: 0.9rem;'>📍 Unit: <span style='font-weight: 600; color: #1e3a8a;'>{row.get('unit','')}</span></div>
                                    {doc_link_section}
                                </div>
                                <div style='flex: 1; text-align: right;'>
                                    <span style='background: {bg}; color: {accent}; padding: 8px 16px; border-radius: 12px; font-size: 0.75rem; font-weight: 800; border: 1.5px solid {accent}40; text-transform: uppercase;'>
                                        {row.get('p_status') or 'APPROVED'}
                                    </span>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
                else:
                    st.warning("⚠️ Tidak ada kegiatan yang ditemukan untuk kriteria filter ini.")
            else:
                st.info("💡 Belum ada jadwal kegiatan yang terdaftar.")

        except Exception as e:
            st.error(f"Terjadi kesalahan teknis: {e}")

    # ---------------------------------
    # PAGE 3: PENGUJUAN DOKUMENTASI 
    # ----------------------------------
    elif nav == "Pengajuan Dokumentasi":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>📝 Buat Pengajuan Baru</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Lengkapi data di bawah. Sistem akan memvalidasi jadwal secara otomatis.</p>
            </div>
        """, unsafe_allow_html=True)

        try:
            units = pd.read_sql(text("SELECT nama_unit FROM daftar_akun_unit"), engine)['nama_unit'].tolist()
        except: units = []

        with st.container(border=True):
            with st.form("form_pengajuan_utama", clear_on_submit=True):
                # --- SECTION 1: IDENTITAS ---
                st.markdown("<p style='font-weight:800; color:#1e3a8a; border-bottom: 2px solid #e2e8f0; padding-bottom:5px;'>🔘 INFORMASI DASAR</p>", unsafe_allow_html=True)
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    v_kegiatan = st.text_input("📋 Nama Kegiatan", placeholder="Contoh: Rapat Koordinasi Wilayah")
                with c2:
                    v_pengaju = st.text_input("👤 Nama Pengaju", value=st.session_state.user['username'])
                with c3:
                    unit_k = st.text_input("🏢 Unit Kerja", placeholder="Contoh: UP3 Lampung, atau unit lainnya")

                # --- SECTION 2: WAKTU & OUTPUT ---
                st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
                st.markdown("<p style='font-weight:800; color:#1e3a8a; border-bottom: 2px solid #e2e8f0; padding-bottom:5px;'>📅 JADWAL & OUTPUT</p>", unsafe_allow_html=True)
                
                d1, d2, d3 = st.columns(3)
                with d1:
                    tgl_acara = st.date_input("📅 Tanggal Acara", min_value=datetime.now().date())
                with d2:
                    j_mulai = st.time_input("🕐 Jam Mulai")
                with d3:
                    j_selesai = st.time_input("🕑 Jam Selesai")

                o1, o2, o3 = st.columns([1, 1, 1])
                with o1:
                    output_k = st.selectbox("📸 Tipe Output", ["Video", "Foto", "Foto & Video"])
                with o2:
                    biaya_e = st.number_input("💰 Apakah ada Anggaran? (Rp)", min_value=0, step=10000, format="%d")
                with o3:
                    # LOGIKA: Minimal H+1 dari Tanggal Acara
                    min_deadline = tgl_acara + timedelta(days=1)
                    v_deadline = st.date_input(
                        "🏁 Deadline Selesai (Min H+1)", 
                        value=min_deadline,
                        min_value=min_deadline, # User tidak bisa pilih sebelum H+1
                        help="Batas waktu tim menyerahkan hasil dokumentasi (Minimal 1 hari setelah acara)."
                    )

                st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
                st.markdown("<p style='font-weight:800; color:#1e3a8a; border-bottom: 2px solid #e2e8f0; padding-bottom:5px;'>🔗 KONTAK & REFERENSI</p>", unsafe_allow_html=True)
                
                k1, k2 = st.columns([1, 2])
                with k1:
                    telp = st.text_input("📱 WhatsApp Active", placeholder="08xxxxxxxxxx")
                with k2:
                    drive_link = st.text_input("🔗 Link Referensi Drive", placeholder="https://drive.google.com/...")
                
                catatan = st.text_area("📌 Instruksi Khusus (Contoh: Wajib ada Cinematic / Drone)", height=100)
                
                st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
                submit_btn = st.form_submit_button("🚀 KIRIM PENGAJUAN", use_container_width=True)
                
                if submit_btn:
                    if not v_kegiatan or not telp:
                        st.error("❌ Nama Kegiatan dan WhatsApp wajib diisi!")
                    else:
                        nama_final = f"{v_kegiatan} - {v_pengaju}"
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        with engine.begin() as conn:
                            res = conn.execute(text("""
                                INSERT INTO pengajuan_dokumentasi 
                                (nama_pengaju, user_id, nomor_telpon, unit, tanggal_acara, jam_mulai, jam_selesai, 
                                output_link_drive, output_type, biaya, deadline_penyelesaian, status, notes, created_at, updated_at) 
                                VALUES (:np, :uid, :tel, :u, :ta, :jm, :js, :od, :ot, :bi, :dl, 'pending', :nt, :ca, :ua)
                                RETURNING id
                            """), {
                                "np": nama_final, "uid": st.session_state.user['id'], "tel": telp, "u": unit_k, 
                                "ta": tgl_acara.strftime("%d/%m/%Y"), "jm": j_mulai.strftime("%H:%M"), 
                                "js": j_selesai.strftime("%H:%M"), "od": drive_link, "ot": output_k, 
                                "bi": biaya_e, "dl": v_deadline.strftime("%d/%m/%Y"), "nt": catatan, "ca": now_str, "ua": now_str
                            })
                            
                            new_id = res.fetchone()[0]
                            if new_id:
                                conn.execute(text("""
                                    INSERT INTO dokumentasi_calendar (pengajuan_id, tanggal, nama_kegiatan, unit, status, created_at) 
                                    VALUES (:id, :t, :n, :u, 'pending', :ca)
                                """), {"id": new_id, "t": tgl_acara.strftime("%d/%m/%Y"), "n": v_kegiatan, "u": unit_k, "ca": now_str})
                        
                        st.success("✅ Pengajuan Anda telah tercatat dan masuk ke antrean Kalender."); st.balloons(); time.sleep(1); st.rerun()

    # ------------------------------------
    # PAGE 4: RIWAYAT DOKUMENTASI 
    # ------------------------------------
    elif nav == "Riwayat Dokumentasi":
        st.markdown("""
            <div style='background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%); padding: 30px; border-radius: 20px; margin-bottom: 25px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);'>
                <h1 style='color: white; margin: 0; font-size: 28px; font-weight: 700;'>📋 Riwayat Dokumentasi</h1>
                <p style='color: #e0f2fe; margin: 5px 0 0 0; opacity: 0.8;'>Pantau perkembangan dokumentasi dan kelola pengajuan Anda.</p>
            </div>
        """, unsafe_allow_html=True)
        search_q = st.text_input("🔍 Cari Nama Kegiatan / Pengaju", placeholder="Masukkan kata kunci...")
        
        df_history = pd.read_sql(text("SELECT * FROM pengajuan_dokumentasi WHERE user_id = :uid ORDER BY created_at DESC"), 
                                engine, params={"uid": st.session_state.user['id']})
        if not df_history.empty:
            df_history['nama_pengaju'] = df_history['nama_pengaju'].fillna('')
            df_history['status'] = df_history['status'].fillna('pending').str.lower()
            valid_statuses = ['pending', 'approved', 'done', 'rejected']
            df_history['status'] = df_history['status'].apply(lambda x: x if x in valid_statuses else 'pending')
        
        if search_q:
            df_history = df_history[df_history['nama_pengaju'].str.contains(search_q, case=False, na=False)]

        if df_history.empty:
            st.info("Belum ada data riwayat.")
        else:
            st.markdown("<div style='margin-bottom:25px;'></div>", unsafe_allow_html=True)
            for idx, row in df_history.iterrows():
                is_pending = row['status'].lower() == 'pending'
                
                with st.container(border=True):
                    h1, h2 = st.columns([3, 1])
                    with h1:
                        st.markdown(f"<h3 style='margin:0; color:#0f172a;'>📌 {row['nama_pengaju']}</h3>", unsafe_allow_html=True)
                        st.markdown(f"<p style='color:#2563eb; font-weight:700; margin-top:2px; font-size:0.95rem;'>{row['unit']} • 📅 {row['tanggal_acara']}</p>", unsafe_allow_html=True)
                    with h2:
                        status_lower = row['status'].lower()
                        if status_lower == "pending":
                            st_col = "#f59e0b"  
                        elif status_lower == "approved":
                            st_col = "#10b981"  
                        elif status_lower == "done":
                            st_col = "#3b82f6"  
                        elif status_lower == "rejected":
                            st_col = "#ef4444"  
                        else:
                            st_col = "#64748b"  
                        st.markdown(f"<div style='text-align:right;'><span style='background:{st_col}10; color:{st_col}; padding:8px 18px; border-radius:100px; font-size:0.8rem; font-weight:800; border:1px solid {st_col}30;'>{row['status'].upper()}</span></div>", unsafe_allow_html=True)

                    st.markdown("<div style='background:#f8fafc; padding:15px; border-radius:12px; margin:15px 0;'>", unsafe_allow_html=True)
                    i1, i2, i3, i4 = st.columns(4)
                    i1.markdown(f"<small style='color:#64748b;'>WHATSAPP</small><br><b>{row['nomor_telpon']}</b>", unsafe_allow_html=True)
                    i2.markdown(f"<small style='color:#64748b;'>WAKTU</small><br><b>{row['jam_mulai']} - {row['jam_selesai']}</b>", unsafe_allow_html=True)
                    i3.markdown(f"<small style='color:#64748b;'>TIPE</small><br><b>{row['output_type']}</b>", unsafe_allow_html=True)
                    i4.markdown(f"<small style='color:#64748b;'>EST. BIAYA</small><br><b>Rp {int(row['biaya']):,}</b>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                    if row['status'].lower() == 'rejected':
                        st.error("🚫 **Pengajuan Ditolak** - Silahkan ajukan kembali dengan data yang tepat.")
                        rejection_msg = row.get('rejection_reason', 'Tidak ada keterangan')
                        if pd.notna(rejection_msg) and str(rejection_msg).strip():
                            st.markdown(f"<p style='font-size:0.9rem; color:#64748b; font-style:italic;'>**Alasan:** {rejection_msg}</p>", unsafe_allow_html=True)
                        st.markdown("<div style='margin:15px 0;'></div>", unsafe_allow_html=True)
                    
                    if row['status'].lower() == 'done':
                        st.markdown("<p style='font-size:0.85rem; font-weight:800; color:#1e293b; margin-bottom:12px;'>📥 HASIL DOKUMENTASI AKHIR:</p>", unsafe_allow_html=True)
                        
                        o1, o2, o3 = st.columns(3)

                        link_drive = row.get('hasil_link_drive') or row.get('hasil_link_1') or row.get('output_link_drive')
                        link_flyer = row.get('hasil_flyer') or row.get('hasil_link_2')
                        link_video = row.get('hasil_video') or row.get('hasil_link_3')

                        with o1:
                            if link_drive and str(link_drive).strip() not in ['', '#', 'None', 'nan']:
                                st.link_button("📂 Folder Drive", str(link_drive), use_container_width=True)
                            else:
                                st.button("📂 Drive: N/A", disabled=True, use_container_width=True, key=f"btn_drive_{row['id']}")

                        with o2: 
                            if link_video and str(link_video).strip() not in ['', 'None', 'nan']:
                                st.link_button("🎬 Link Video", str(link_video), use_container_width=True)
                            else:
                                st.button("🎬 Video: N/A", disabled=True, use_container_width=True, key=f"btn_video_{row['id']}")

                        with o3:
                            if link_flyer and str(link_flyer).strip() not in ['', 'None', 'nan']:
                                st.link_button("🖼️ Link Flyer", str(link_flyer), use_container_width=True)
                            else:
                                st.button("🖼️ Flyer: N/A", disabled=True, use_container_width=True, key=f"btn_flyer_{row['id']}")
                    
                    elif is_pending:
                       
                        show_key = f"show_form_{row['id']}"
                        if show_key not in st.session_state:
                            st.session_state[show_key] = False

                        col_edit, col_cancel = st.columns(2)
                        
                        btn_label = "❌ BATAL EDIT" if st.session_state[show_key] else "🛠️ EDIT PENGAJUAN"
                        with col_edit:
                            if st.button(btn_label, key=f"btn_edit_{row['id']}", use_container_width=True):
                                st.session_state[show_key] = not st.session_state[show_key]
                                st.rerun()
                        
                        with col_cancel:
                            if st.button("🗑️ BATALKAN PENGAJUAN", key=f"btn_cancel_{row['id']}", use_container_width=True):
                                st.session_state[f"confirm_cancel_{row['id']}"] = True
                        
                        if st.session_state.get(f"confirm_cancel_{row['id']}", False):
                            st.warning(f"⚠️ Yakin ingin membatalkan pengajuan '{row['nama_pengaju']}'?")
                            col_confirm, col_cancel_confirm = st.columns(2)
                            with col_confirm:
                                if st.button("✅ Ya, Batalkan", key=f"confirm_cancel_ok_{row['id']}", use_container_width=True):
                                    with engine.begin() as conn:
                                        conn.execute(text("DELETE FROM pengajuan_dokumentasi WHERE id=:id"), {"id": row['id']})
                                        conn.execute(text("DELETE FROM dokumentasi_calendar WHERE pengajuan_id=:id"), {"id": row['id']})
                                    st.toast(f"✅ Pengajuan '{row['nama_pengaju']}' telah dibatalkan", icon="✅")
                                    st.session_state[f"confirm_cancel_{row['id']}"] = False
                                    time.sleep(0.5)
                                    st.rerun()
                            with col_cancel_confirm:
                                if st.button("❌ Tetap Lanjut", key=f"cancel_cancel_{row['id']}", use_container_width=True):
                                    st.session_state[f"confirm_cancel_{row['id']}"] = False
                                    st.rerun()

                        if st.session_state[show_key]:
                            with st.form(f"form_revisi_{row['id']}", border=False):
                                st.markdown("<h4 style='color:#1e293b; margin-top:0;'>📝 Form Revisi Data</h4>", unsafe_allow_html=True)
                                
                                parts = row['nama_pengaju'].split(" - ")
                                c1, c2 = st.columns(2)
                                with c1:
                                    en_keg = st.text_input("Nama Kegiatan", value=parts[0] if len(parts)>0 else "")
                                    en_peng = st.text_input("Nama Pengaju", value=parts[1] if len(parts)>1 else "")
                                    en_out = st.selectbox("Tipe Output", ["Video", "Foto", "Foto & Video"], 
                                                        index=["Video", "Foto", "Foto & Video"].index(row['output_type']) if row['output_type'] in ["Video", "Foto", "Foto & Video"] else 0)
                                with c2:
                                    en_wa = st.text_input("WhatsApp", value=row['nomor_telpon'])
                                    en_tgl = st.date_input("Tanggal Acara", value=datetime.strptime(row['tanggal_acara'], "%d/%m/%Y") if "/" in row['tanggal_acara'] else datetime.now())
                                    en_biaya = st.number_input("Estimasi Biaya", value=int(row['biaya']))

                                st.markdown("<div style='margin-top:15px;'></div>", unsafe_allow_html=True)
                                ec3, ec4, ec5 = st.columns(3)
                                with ec3:
                                    en_jm = st.time_input("Jam Mulai", value=datetime.strptime(row['jam_mulai'], "%H:%M").time() if ":" in str(row['jam_mulai']) else datetime.now().replace(hour=8, minute=0).time())
                                with ec4:
                                    en_js = st.time_input("Jam Selesai", value=datetime.strptime(row['jam_selesai'], "%H:%M").time() if ":" in str(row['jam_selesai']) else datetime.now().replace(hour=17, minute=0).time())
                                with ec5: en_dl = st.date_input("Deadline", value=en_tgl + timedelta(days=2))

                                en_drive = st.text_input("Link Drive Referensi", value=row['output_link_drive'])
                                en_note = st.text_area("Catatan", value=row['notes'])

                                st.markdown("<div style='margin-top:20px;'></div>", unsafe_allow_html=True)
                                if st.form_submit_button("🚀 SIMPAN PERUBAHAN"):
                                    new_name = f"{en_keg} - {en_peng}"
                                    with engine.begin() as conn:
                            
                                        conn.execute(text("""UPDATE pengajuan_dokumentasi SET 
                                            nama_pengaju=:np, nomor_telpon=:wa, unit=:u, tanggal_acara=:ta, 
                                            jam_mulai=:jm, jam_selesai=:js, output_link_drive=:od, 
                                            output_type=:ot, biaya=:bi, notes=:nt, updated_at=:ua 
                                            WHERE id=:id"""),
                                        {
                                            "np": new_name, "wa": en_wa, "u": row['unit'], 
                                            "ta": en_tgl.strftime("%d/%m/%Y"), "jm": en_jm.strftime("%H:%M"), 
                                            "js": en_js.strftime("%H:%M"), "od": en_drive, "ot": en_out, 
                                            "bi": en_biaya, "nt": en_note, "ua": datetime.now(), "id": row['id']
                                        })
                                        conn.execute(text("""UPDATE dokumentasi_calendar SET 
                                            tanggal=:ta, nama_kegiatan=:nk, unit=:u 
                                            WHERE pengajuan_id=:id"""),
                                        {
                                            "ta": en_tgl.strftime("%d/%m/%Y"), "nk": en_keg, "u": row['unit'], "id": row['id']
                                        })
                                    st.success("✅ Berhasil Disimpan!")
                                    st.session_state[show_key] = False
                                    st.rerun()

                    else:
                        st.info("ℹ️ Sedang diproses oleh tim. Anda tidak dapat mengubah data saat ini.")

                st.markdown("<div style='margin-bottom:20px;'></div>", unsafe_allow_html=True)

# ============ FOOTER ============
FOOTER_CSS = """
<style>
/* Footer specific CSS placed next to footer markup */
.stContainer, .stExpander { background: #ffffff !important; border: 1px solid rgba(0, 170, 180, 0.1) !important; border-radius: 12px !important; box-shadow: 0 4px 12px rgba(0,0,0,0.02) !important; }
.app-footer { position: fixed; bottom: 0; left: 0; right: 0; width: 100%; background: linear-gradient(90deg, #60a5fa 0%, #3b82f6 100%); padding: 10px 0; z-index: 9999; box-shadow: 0 -3px 15px rgba(0, 0, 0, 0.08); }
.footer-container { max-width: 95%; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; }
.footer-left { display: flex; align-items: center; gap: 10px; flex: 1; }
.footer-left h4 { margin: 0 !important; padding: 0 !important; font-size: 13px !important; font-weight: 800 !important; color: #ffffff !important; }
.footer-center { flex: 1; text-align: center; }
.footer-center p { margin: 0 !important; font-size: 11px !important; color: #ffffff !important; font-weight: 500; opacity: 0.9; }
.footer-right { display: flex; justify-content: flex-end; align-items: center; flex: 1; }
.status-box { display: flex; align-items: center; gap: 8px; background: rgba(255,255,255,1); padding: 4px 12px; border-radius: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.status-box .dot { width: 7px; height: 7px; background: #10b981; border-radius: 50%; animation: blink 1.5s infinite; }
.status-box .status-text { font-size: 10px; font-weight: 700; color: #1e40af; text-transform: uppercase; letter-spacing: 0.5px; }
@keyframes blink { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.9); } 100% { opacity: 1; transform: scale(1); } }
.stMainBlockContainer { padding-bottom: 50px !important; }
@media (max-width: 768px) { .footer-center { display: none; } .footer-left h4 { font-size: 11px !important; } }
</style>
"""

footer_html = """
<div class='app-footer'>
    <div class='footer-container'>
        <div class='footer-left'>
            <h4>⚡ PLN UID LAMPUNG</h4>
        </div>
        <div class='footer-center'>
            <p>&copy; 2026 PT PLN (Persero) UID Lampung</p>
        </div>
        <div class='footer-right'>
            <div class='status-box'>
                <span class='dot'></span>
                <span class='status-text'>System Online</span>
            </div>
        </div>
    </div>
</div>
"""

st.markdown(FOOTER_CSS + footer_html, unsafe_allow_html=True)