import sqlite3

conn = sqlite3.connect('app_data.db')
c = conn.cursor()

rows = c.execute("SELECT ip, hostname, alias FROM devices WHERE hostname IS NOT NULL OR alias IS NOT NULL").fetchall()
print(f"Total with hostname/alias: {len(rows)}")
for r in rows:
    print(r)

conn.close()
