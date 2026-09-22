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
        # Verifica janelas no display :0 e :1
        w0=$(DISPLAY=:0 wmctrl -l 2>/dev/null || DISPLAY=:0 xwininfo -root -tree 2>/dev/null | grep -iE 'matific|chrome|firefox' || echo "")
        w1=$(DISPLAY=:1 wmctrl -l 2>/dev/null || DISPLAY=:1 xwininfo -root -tree 2>/dev/null | grep -iE 'matific|chrome|firefox' || echo "")
        
        echo "HOST=$hostname | JANELAS_DISP_0=[$w0] | JANELAS_DISP_1=[$w1]"
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

print("\n=== JANELAS ABERTAS EM :0 E :1 ===")
for ip, ok, res in results:
    if ok:
        print(f"{ip}: {res}")
    else:
        print(f"{ip}: OFFLINE / ERRO ({res})")
