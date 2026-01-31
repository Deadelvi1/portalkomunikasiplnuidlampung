import sqlite3, hashlib, os, time
DB = os.path.abspath('PLN_Ultimate_Monitoring_V7.db')
conn = sqlite3.connect(DB)
conn.execute('PRAGMA journal_mode=WAL')
cur = conn.cursor()
new_hash = hashlib.sha256('admin123'.encode()).hexdigest()
cur.execute('UPDATE users SET password = ? WHERE username = ?', (new_hash, 'admin'))
conn.commit()
print('updated rows:', cur.rowcount)
# verify
time.sleep(0.1)
cur.execute('SELECT password FROM users WHERE username = ?', ('admin',))
print('stored:', cur.fetchone()[0])
conn.close()
