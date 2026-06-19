import sqlite3
conn = sqlite3.connect('data/pulso.db')
for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print(r)
