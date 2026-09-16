import sqlite3
import os

for db_path in ['app_data.db', 'menu.db']:
    if os.path.exists(db_path):
        print(f"=== {db_path} ===")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print("Tables:", tables)
        for t in tables:
            rows = c.execute(f"SELECT * FROM {t}").fetchall()
            print(f"Table {t} ({len(rows)} rows):")
            for r in rows[:15]:
                print("  ", r)
        conn.close()
