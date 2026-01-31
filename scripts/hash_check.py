import hashlib
for p in ['admin','admin123','password','123456']:
    print(p, hashlib.sha256(p.encode()).hexdigest())
