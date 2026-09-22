# -*- coding: utf-8 -*-
import paramiko
from concurrent.futures import ThreadPoolExecutor, as_completed

ips = [f"192.168.50.{i}" for i in range(51, 75)]

def check_ip(ip):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username='aluno', password='qwe123', timeout=2, banner_timeout=3)
        
        cmd = r"""
        hostname=$(hostname)
        has_matific=$(pgrep -f 'matific' 2>/dev/null && echo "SIM" || echo "NAO")
        running_browser=$(pgrep -x google-chrome || pgrep -x firefox || pgrep -x chromium || echo "NENHUM")
        disp=$(ps -u aluno -o args 2>/dev/null | grep -oP ':[0-9]+' | head -n 1)
        [ -z "$disp" ] && disp=":0"
        echo "HOST=$hostname | MATIFIC_RODANDO=$has_matific | BROWSER_PID=$running_browser | DISP=$disp"
        """
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=4)
        out = stdout.read().decode('utf-8', errors='replace').strip()
        ssh.close()
        return ip, True, out
    except Exception as e:
        return ip, False, str(e)

results = []
with ThreadPoolExecutor(max_workers=25) as executor:
    futures = {executor.submit(check_ip, ip): ip for ip in ips}
    for f in as_completed(futures):
        results.append(f.result())

results.sort(key=lambda x: int(x[0].split('.')[-1]))

print("\n=== RESULTADO DETALHADO DAS MÁQUINAS ===")
for ip, ok, res in results:
    if ok:
        print(f"{ip}: {res}")
    else:
        print(f"{ip}: OFFLINE / ERRO ({res})")
