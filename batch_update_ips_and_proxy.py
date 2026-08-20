#!/usr/bin/env python3
"""
==============================================================================
Script de Automação SSH para Atualização de IP (192.168.0.x -> 192.168.1.x)
e Remoção de Proxy em Lote
==============================================================================
"""

import sys
import os
import time
import logging
import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("batch_network_update")

try:
    import paramiko
except ImportError:
    logger.error("Paramiko não instalado. Instale executando: pip install paramiko")
    sys.exit(1)

# Import do ssh_service do projeto menu se disponível
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from ssh_service import ssh_connect
except ImportError:
    ssh_connect = None

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "change_ips_and_disable_proxy.sh")

def load_target_ips(start_ip=101, end_ip=150, old_prefix="192.168.0."):
    """Carrega lista de IPs alvos. Prioriza conhecidos em blocklist/known_macs se existirem."""
    ips = []
    
    # Adiciona faixa padrão especificada pelo usuário
    for i in range(start_ip, end_ip + 1):
        ips.append(f"{old_prefix}{i}")

    # Verifica se existem arquivos no projeto para adicionar outros IPs conhecidos
    for json_file in ["known_macs.json.bak", "ip_blocklist.json"]:
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), json_file)
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        keys = list(data.keys())
                    elif isinstance(data, list):
                        keys = data
                    else:
                        keys = []
                    for item in keys:
                        if isinstance(item, str) and item.startswith(old_prefix) and item not in ips:
                            ips.append(item)
            except Exception as e:
                logger.debug(f"Erro lendo {json_file}: {e}")

    # Ordena numericamente pelo último octeto
    def sort_key(ip):
        try: return int(ip.split('.')[-1])
        except: return 0
    return sorted(list(set(ips)), key=sort_key)

def process_machine(old_ip, username="aluno", password="1", old_prefix="192.168.0.", new_prefix="192.168.1.", new_gateway="192.168.1.1"):
    """Conecta na máquina via SSH, envia o script, executa a alteração e verifica o novo IP."""
    last_oct = old_ip.split('.')[-1]
    expected_new_ip = f"{new_prefix}{last_oct}"
    
    logger.info(f"[{old_ip}] Tentando conectar via SSH...")

    # Verifica se a porta 22 responde
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    result = sock.connect_ex((old_ip, 22))
    sock.close()
    if result != 0:
        logger.warning(f"[{old_ip}] Porta SSH 22 inacessível (Offline ou IP inativo).")
        return {"old_ip": old_ip, "new_ip": expected_new_ip, "status": "OFFLINE"}

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(old_ip, username=username, password=password, timeout=10, look_for_keys=False)

        # Envia o script de shell
        sftp = ssh.open_sftp()
        remote_script = "/tmp/change_ips_and_disable_proxy.sh"
        sftp.put(SCRIPT_PATH, remote_script)
        sftp.chmod(remote_script, 0o755)
        sftp.close()

        # Executa o script com privilégios de root (via sudo -S)
        cmd = f"echo '{password}' | sudo -S bash {remote_script} '{old_prefix}' '{new_prefix}' '{new_gateway}'"
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=30)
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')

        ssh.close()

        logger.info(f"[{old_ip}] Script executado com sucesso! Novo IP agendado para: {expected_new_ip}")
        return {"old_ip": old_ip, "new_ip": expected_new_ip, "status": "SUCCESS", "details": out}

    except Exception as e:
        logger.error(f"[{old_ip}] Falha ao processar: {e}")
        return {"old_ip": old_ip, "new_ip": expected_new_ip, "status": "ERROR", "error": str(e)}

def verify_new_ip(new_ip):
    """Testa se o novo IP responde via ping/socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    res = sock.connect_ex((new_ip, 22))
    sock.close()
    return res == 0

def main():
    print("=" * 80)
    print(" FERRAMENTA DE ATUALIZAÇÃO DE IP DE REDE E DESATIVAÇÃO DE PROXY ")
    print(" De: 192.168.0.x  --->  Para: 192.168.1.x ")
    print("=" * 80)

    old_prefix = os.getenv("OLD_PREFIX", "192.168.0.")
    new_prefix = os.getenv("NEW_PREFIX", "192.168.1.")
    new_gateway = os.getenv("NEW_GATEWAY", "192.168.1.1")
    username = os.getenv("SSH_USER", "aluno")
    password = os.getenv("SSH_PASS", "1")

    targets = load_target_ips(101, 150, old_prefix=old_prefix)
    print(f"[i] {len(targets)} máquinas identificadas para atualização (ex: {targets[:3]} ... {targets[-1:]})")
    print(f"[i] Credenciais SSH utilizadas: usuário='{username}', senha='{password}'")
    print("-" * 80)

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(process_machine, ip, username, password, old_prefix, new_prefix, new_gateway): ip
            for ip in targets
        }
        for future in as_completed(futures):
            res = future.result()
            results.append(res)

    print("\n" + "=" * 80)
    print(" RESUMO DA OPERAÇÃO ")
    print("=" * 80)
    success_count = sum(1 for r in results if r['status'] == 'SUCCESS')
    offline_count = sum(1 for r in results if r['status'] == 'OFFLINE')
    error_count = sum(1 for r in results if r['status'] == 'ERROR')

    print(f"✓ Sucesso (Instrução enviada): {success_count}")
    print(f"⚡ Inacessíveis / Offline:    {offline_count}")
    print(f"✗ Erros:                    {error_count}\n")

    if success_count > 0:
        print("[+] Aguardando 5 segundos para a transição das interfaces de rede nas máquinas...")
        time.sleep(5)
        print("[+] Testando conectividade nos novos IPs (192.168.1.x)...")
        verified = 0
        for r in results:
            if r['status'] == 'SUCCESS':
                if verify_new_ip(r['new_ip']):
                    print(f"  ✓ {r['old_ip']} -> {r['new_ip']} [CONFIRMADO ONLINE]")
                    verified += 1
                else:
                    print(f"  ? {r['old_ip']} -> {r['new_ip']} [Ainda em reinicialização ou gateway requer verificação]")
        print(f"\n[+] Total de confirmações no novo IP: {verified}/{success_count}")

if __name__ == "__main__":
    main()
