import sqlite3

conn = sqlite3.connect('app_data.db')
c = conn.cursor()
rows = c.execute("SELECT ip, mac, alias, is_blocked, hostname, group_name FROM devices").fetchall()
print(f"Total devices: {len(rows)}")
for r in rows:
    if r[4] or r[2]:  # hostname or alias
        print(r)

conn.close()
