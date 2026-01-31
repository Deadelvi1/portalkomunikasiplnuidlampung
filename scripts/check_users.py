import sqlite3, hashlib, os
DB = os.path.abspath('PLN_Ultimate_Monitoring_V7.db')
conn = sqlite3.connect(DB)
cur = conn.cursor()
try:
    cur.execute('SELECT id, username, password, role FROM users')
    rows = cur.fetchall()
    print('FOUND', len(rows), 'users')
    for r in rows:
        print(r[0], r[1], r[2][:32]+'...' if r[2] else None, r[3])
except Exception as e:
    print('ERROR', e)
finally:
    conn.close()
