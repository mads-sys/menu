# -*- coding: utf-8 -*-
import paramiko
from concurrent.futures import ThreadPoolExecutor, as_completed

ips = [f"192.168.50.{i}" for i in range(51, 75)]

def check_ip(ip):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username='aluno', password='qwe123', timeout=3, banner_timeout=5)
        
        cmd = r"""
        echo "=== HOST: $(hostname) ==="
        echo "USERS: $(who 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')"
        echo "LOGGED_X_SESSIONS: $(ls -d /run/user/[0-9]* 2>/dev/null | while read d; do uid=$(basename "$d"); user=$(getent passwd "$uid" | cut -d: -f1); echo "$user(uid=$uid)"; done | tr '\n' ' ')"
        echo "DISPLAYS: $(ps -ef 2>/dev/null | grep -oE ':[0-9]+' | sort -u | tr '\n' ' ')"
        echo "DEFAULT_BROWSER: $(xdg-settings get default-web-browser 2>/dev/null || echo 'N/A')"
        echo "INSTALLED_BROWSERS: $(which google-chrome chromium-browser chromium firefox brave-browser opera 2>/dev/null | tr '\n' ' ')"
        echo "RUNNING_BROWSERS: $(pgrep -a -f 'chrome|firefox|chromium' 2>/dev/null | head -n 3 | tr '\n' ' ')"
        echo "XDG_OPEN_STATUS: $(which xdg-open 2>/dev/null || echo 'SEM_XDG')"
        """
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=5)
        out = stdout.read().decode('utf-8', errors='replace').strip()
        ssh.close()
        return ip, True, out
    except Exception as e:
        return ip, False, str(e)

print("Iniciando diagnostico detalhado das 22 maquinas com SSH...")
with ThreadPoolExecutor(max_workers=25) as executor:
    futures = {executor.submit(check_ip, ip): ip for ip in ips}
    for f in as_completed(futures):
        ip, ok, res = f.result()
        if ok:
            print(f"[{ip}] OK:\n{res}\n")
        else:
            print(f"[{ip}] FALHA: {res}\n")
