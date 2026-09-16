import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from app import ssh_connect, SSH_USER
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

for ip in ['192.168.0.106', '192.168.0.107']:
    try:
        with ssh_connect(ip, SSH_USER, 'batatais', logger) as ssh:
            stdin, stdout, stderr = ssh.exec_command('hostname; cat /etc/hostname')
            print(f"IP {ip} SSH hostname output:", stdout.read().decode())
    except Exception as e:
        print(f"IP {ip} SSH failed with password 'batatais':", e)
        try:
            with ssh_connect(ip, SSH_USER, 'qwe123', logger) as ssh:
                stdin, stdout, stderr = ssh.exec_command('hostname; cat /etc/hostname')
                print(f"IP {ip} SSH hostname output (qwe123):", stdout.read().decode())
        except Exception as e2:
            print(f"IP {ip} SSH failed with qwe123:", e2)
