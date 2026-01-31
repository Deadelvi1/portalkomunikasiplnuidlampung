import sqlite3, hashlib, os, time
DB = os.path.abspath('PLN_Ultimate_Monitoring_V7.db')
conn = sqlite3.connect(DB)
conn.execute('PRAGMA journal_mode=WAL')
cur = conn.cursor()
newpass = 'tempPass123'
newhash = hashlib.sha256(newpass.encode()).hexdigest()
cur.execute('UPDATE users SET password = ? WHERE username = ?', (newhash, 'dea'))
conn.commit()
print('updated rows:', cur.rowcount)
# small delay
time.sleep(0.1)
cur.execute('SELECT id FROM users WHERE username = ? AND password = ?', ('dea', newhash))
print('login OK' if cur.fetchone() else 'login FAIL')
conn.close()
