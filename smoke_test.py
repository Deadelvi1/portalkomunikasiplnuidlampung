#!/usr/bin/env python3
"""Smoke test for PLN app DB flows.
Run: python smoke_test.py
This script performs non-destructive checks and a set of simple inserts/updates to validate
pengajuan <-> dokumentasi_calendar <-> monitoring_pln flows. It uses the same DB file as the app.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.abspath("PLN_Ultimate_Monitoring_V7.db")

print("DB path:", DB_PATH)
if not os.path.exists(DB_PATH):
    print("ERROR: database file not found.")
    raise SystemExit(1)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

def safe_fetchone(q, params=()):
    cur.execute(q, params)
    return cur.fetchone()

print("Checking required tables...")
for t in ['users','daftar_akun_unit','pengajuan_dokumentasi','dokumentasi_calendar','monitoring_pln']:
    r = safe_fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,))
    print(f" - {t}:", 'OK' if r else 'MISSING')

print('\nChecking unique index on monitoring_pln.link_pemberitaan...')
cur.execute("PRAGMA index_list('monitoring_pln')")
indexes = cur.fetchall()
print('Indexes found:', indexes)

# Get admin id
admin = safe_fetchone("SELECT id FROM users WHERE username='admin'")
admin_id = admin[0] if admin else None
print('\nAdmin id:', admin_id)

# Insert a test unit
print('\nInserting test unit...')
cur.execute("INSERT OR IGNORE INTO daftar_akun_unit (nama_unit, username_ig) VALUES (?,?)", ("UNIT_TEST", "unit_test_ig"))
conn.commit()
print('Unit inserted.')

# Create a pengajuan
print('\nCreating test pengajuan...')
now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
cur.execute("INSERT INTO pengajuan_dokumentasi (nama_pengaju, user_id, nomor_telpon, unit, tanggal_acara, jam_mulai, jam_selesai, output_link_drive, output_type, biaya, status, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("Test Kegiatan - Tester", admin_id, "081234567890", "UNIT_TEST", "05/01/2026", "08:00", "10:00", "", "Foto & Video", 0, 'pending', 'Smoke test', now, now))
conn.commit()
pid = cur.lastrowid
print('Pengajuan id:', pid)

# Create calendar event for that pengajuan
print('\nInserting calendar event...')
cur.execute("INSERT INTO dokumentasi_calendar (pengajuan_id, tanggal, nama_kegiatan, unit, status, created_at) VALUES (?,?,?,?,?,?)",
            (pid, "05/01/2026", "Test Kegiatan", "UNIT_TEST", 'pending', now))
conn.commit()
print('Calendar event created.')

# Update pengajuan to approved and then done with hasil links
print('\nUpdating pengajuan to approved and then done...')
cur.execute("UPDATE pengajuan_dokumentasi SET status='approved' WHERE id=?", (pid,))
conn.commit()
cur.execute("UPDATE dokumentasi_calendar SET status='approved' WHERE pengajuan_id=?", (pid,))
conn.commit()

# Fill hasil and mark done
cur.execute("UPDATE pengajuan_dokumentasi SET status='done', hasil_link_1=?, hasil_link_2=?, hasil_link_3=?, hasil_link_drive=?, hasil_flyer=?, hasil_video=?, updated_at=? WHERE id=?",
            ("https://drive.example/folder", "https://drive.example/foto.jpg", "https://drive.example/video.mp4", "https://drive.example/folder", "https://drive.example/foto.jpg", "https://drive.example/video.mp4", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), pid))
conn.commit()
cur.execute("UPDATE dokumentasi_calendar SET status='done' WHERE pengajuan_id=?", (pid,))
conn.commit()
print('Pengajuan marked done and hasil links saved.')

# Test monitoring_pln unique constraint + ON CONFLICT behaviour (requires unique index)
print('\nTesting monitoring_pln insert ON CONFLICT...')
link = 'https://test.post/123'
try:
    cur.execute("INSERT INTO monitoring_pln (tanggal, bulan, tahun, judul_pemberitaan, link_pemberitaan, platform, tipe_konten, pic_unit, akun, kategori, likes, comments, views, last_updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(link_pemberitaan) DO UPDATE SET likes=excluded.likes, last_updated=excluded.last_updated",
                ("05/01/2026","Januari","2026","Test Post", link, "Instagram","Feeds","UNIT_TEST","@unit_test","Korporat", 1, 0, 0, now))
    conn.commit()
    print('First insert with ON CONFLICT succeeded.')
    # insert again with different likes to trigger update path
    cur.execute("INSERT INTO monitoring_pln (tanggal, bulan, tahun, judul_pemberitaan, link_pemberitaan, platform, tipe_konten, pic_unit, akun, kategori, likes, comments, views, last_updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(link_pemberitaan) DO UPDATE SET likes=excluded.likes, last_updated=excluded.last_updated",
                ("05/01/2026","Januari","2026","Test Post Updated", link, "Instagram","Feeds","UNIT_TEST","@unit_test","Korporat", 5, 0, 0, now))
    conn.commit()
    print('Second insert (conflict) succeeded — should have updated likes to 5')
    cur.execute("SELECT likes FROM monitoring_pln WHERE link_pemberitaan=?", (link,))
    print('Likes now:', cur.fetchone()[0])
except Exception as e:
    print('ERROR while testing monitoring_pln ON CONFLICT:', e)

print('\nSummary counts:')
cur.execute("SELECT COUNT(*) FROM pengajuan_dokumentasi")
print('pengajuan_dokumentasi:', cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM dokumentasi_calendar")
print('dokumentasi_calendar:', cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM monitoring_pln")
print('monitoring_pln:', cur.fetchone()[0])

print('\nSmoke test finished. If all steps above succeeded, core DB flows are working.')
conn.close()
