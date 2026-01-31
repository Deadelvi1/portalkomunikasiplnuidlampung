import sqlite3, hashlib, os
DB = os.path.abspath('PLN_Ultimate_Monitoring_V7.db')
conn = sqlite3.connect(DB)
cur = conn.cursor()
password = 'admin123'
h = hashlib.sha256(password.encode()).hexdigest()
cur.execute('SELECT id, username FROM users WHERE username=? AND password=?', ('admin', h))
row = cur.fetchone()
print('login OK' if row else 'login FAIL', row)
conn.close()
