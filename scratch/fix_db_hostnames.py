import sqlite3

conn = sqlite3.connect('app_data.db')
c = conn.cursor()

# 1. Atualizar hostnames do laboratório EABA (192.168.0.101 até 192.168.0.130)
for i in range(1, 31):
    ip = f'192.168.0.{100 + i}'
    name = f'EABA{i:02d}'
    c.execute('UPDATE devices SET hostname = ? WHERE ip = ?', (name, ip))

# 2. Atualizar hostnames do laboratório Padre (192.168.50.51 até 192.168.50.80)
for i in range(1, 31):
    ip = f'192.168.50.{50 + i}'
    name = f'padre{i:02d}'
    c.execute('UPDATE devices SET hostname = ? WHERE ip = ?', (name, ip))

# 3. Limpar qualquer IP fora do padrão que tenha ficado com EABA16
c.execute("UPDATE devices SET hostname = NULL WHERE hostname = 'EABA16' AND ip NOT IN ('192.168.0.116', '192.168.0.16')")

conn.commit()

# Exibir resultado
rows = c.execute("SELECT ip, hostname FROM devices WHERE ip LIKE '192.168.0.1%' ORDER BY ip").fetchall()
print("EABA IPs corrigidos:")
for r in rows:
    print(f"  {r[0]} -> {r[1]}")

conn.close()
