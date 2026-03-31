import os
import socket
import platform
import subprocess
import ipaddress
import re
import time
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configurações de Rede (Sincronizadas com o Ambiente) ---
FORCE_STATIC_RANGE = os.getenv("FORCE_STATIC_RANGE", "false").lower() == "true"
IP_PREFIX_DEFAULT = os.getenv("IP_PREFIX", "192.168.50.")
IP_START = 1
IP_END = 254
IS_WSL = 'microsoft' in platform.uname().release.lower()
SYSTEM = platform.system()

_NMAP_PATH_CACHE = None

def is_valid_ip(ip: str) -> bool:
    """Valida se a string fornecida é um endereço IP válido."""
    try:
        addr = ipaddress.ip_address(ip)
        return not addr.is_multicast and not addr.is_loopback
    except ValueError:
        return False

def _get_default_gateway() -> Optional[str]:
    try:
        if IS_WSL:
            # No WSL, tenta pegar o gateway físico do Windows
            gw = _get_windows_gateway_info('gateway')
            if gw: return gw
            
        if SYSTEM == "Linux":
            result = subprocess.run(['ip', 'route'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if line.startswith('default via'):
                    return line.split()[2]
        elif SYSTEM == "Windows":
            result = subprocess.run(['route', 'print', '0.0.0.0'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 4 and parts[0] == '0.0.0.0':
                    if is_valid_ip(parts[2]):
                        return parts[2]
    except Exception: pass
    return None

def _get_windows_gateway_info(target: str = 'interface') -> Optional[str]:
    """Busca gateway ou IP da interface no Windows via route.exe."""
    try:
        result = subprocess.run(['route.exe', 'print', '0.0.0.0'], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 4 and parts[0] == '0.0.0.0':
                val = parts[2] if target == 'gateway' else parts[3]
                if is_valid_ip(val):
                    return val
    except Exception: pass
    return None

def get_local_ip_and_range() -> tuple:
    """Detecta dinamicamente o IP local e define a faixa de busca."""
    if FORCE_STATIC_RANGE:
        gateway_ip = _get_default_gateway()
        ip_prefix = IP_PREFIX_DEFAULT
        nmap_range = f"{ip_prefix}0/24"
        ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
        return ip_prefix, nmap_range, ips_to_check, None, gateway_ip

    base_ip = None
    if IS_WSL:
        base_ip = _get_windows_gateway_info('interface')
    elif SYSTEM == "Linux":
        try:
            # Tenta hostname -I que é mais direto no Linux/Ubuntu
            res = subprocess.run(['hostname', '-I'], capture_output=True, text=True)
            ips = res.stdout.strip().split()
            # Pega o primeiro IP que não seja virtual (Docker/172.x) se possível
            base_ip = next((ip for ip in ips if not ip.startswith('172.')), ips[0] if ips else None)
        except: pass
    else:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                base_ip = s.getsockname()[0]
        except Exception:
            try:
                base_ip = socket.gethostbyname(socket.gethostname())
            except Exception: base_ip = None

    if base_ip and not base_ip.startswith('127.'):
        gateway_ip = _get_default_gateway()
        ip_prefix = ".".join(base_ip.split('.')[:-1]) + "."
        nmap_range = f"{ip_prefix}0/24"
        ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
        return ip_prefix, nmap_range, ips_to_check, base_ip, gateway_ip

    ip_prefix = IP_PREFIX_DEFAULT
    return ip_prefix, f"{ip_prefix}0/24", [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)], None, _get_default_gateway()

def _find_windows_nmap() -> str:
    global _NMAP_PATH_CACHE
    if _NMAP_PATH_CACHE: return _NMAP_PATH_CACHE
    
    # 1. Tenta localizar no PATH via PowerShell
    result = subprocess.run(["powershell.exe", "-Command", "Get-Command nmap.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source"], capture_output=True, text=True)
    path = result.stdout.strip()
    if not path:
        # 2. Tenta caminhos de instalação padrão
        for p in ["C:\\Program Files (x86)\\Nmap\\nmap.exe", "C:\\Program Files\\Nmap\\nmap.exe"]:
            if "True" in subprocess.run(["powershell.exe", "-Command", f"Test-Path '{p}'"], capture_output=True, text=True).stdout:
                path = p; break
    _NMAP_PATH_CACHE = f'"{path}"' if path else "nmap"
    return _NMAP_PATH_CACHE

def check_host_online(ip: str) -> Optional[dict]:
    """Verifica se um host está online via SSH ou Ping."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0) # Timeout mais rápido para varredura paralela
    try:
        if sock.connect_ex((ip, 22)) == 0:
            return {'ip': ip, 'type': 'ssh'}
    except Exception: pass
    finally: sock.close()

    # Fallback: Tenta Ping se o SSH falhou
    try:
        is_windows = SYSTEM == 'Windows'
        # Aumentamos o timeout para 2 segundos para lidar com redes instáveis
        cmd = ['ping', '-n' if is_windows else '-c', '1', '-W' if not is_windows else '-w', '2' if not is_windows else '2000', ip]
        if subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3) == 0:
            return {'ip': ip, 'type': 'ping'}
    except: pass
    
    return None

def discover_ips_with_nmap(ip_range: str) -> Optional[List[dict]]:
    try:
        if IS_WSL:
            nmap_exe = _find_windows_nmap()
            command = ["powershell.exe", "-Command", f"& {nmap_exe} -p 22 -T4 --open -oG - {ip_range}"]
        else:
            command = ["nmap", "-p", "22", "-T4", "--open", "-oG", "-", ip_range]

        # Tenta UTF-8 e CP850 para suportar diferentes terminais Windows/Linux
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60, encoding='utf-8')
        except UnicodeDecodeError:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60, encoding='cp850')
            
        active_hosts = {} # Usamos dicionário para evitar duplicatas de IP nas linhas de status/porta
        for line in result.stdout.splitlines():
            if "Host:" not in line: continue
            parts = line.split()
            if len(parts) < 2: continue
            ip = parts[1]
            
            if "/open/tcp" in line:
                active_hosts[ip] = 'ssh'
            elif "Status: Up" in line or "/closed/tcp" in line:
                # Se o host está Up ou a porta respondeu (mesmo fechada), ele está online.
                if ip not in active_hosts or active_hosts[ip] != 'ssh':
                    active_hosts[ip] = 'ping'
        
        return [{'ip': ip, 'type': t} for ip, t in active_hosts.items()]
    except Exception: return None

def discover_ips_with_arp_scan() -> Optional[List[dict]]:
    if IS_WSL: return None
    try:
        command = ["sudo", "arp-scan", "--localnet", "--numeric", "--quiet"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        active_ips = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].count('.') == 3 and is_valid_ip(parts[0]):
                active_ips.append({'ip': parts[0], 'type': 'ping'}) # ARP confirma que está UP, mas não o serviço
        return active_ips
    except Exception: return None

class NetworkScanner:
    def __init__(self, logger):
        self.logger = logger

    def _check_ssh_ports_in_parallel(self, ips: List[str]) -> List[dict]:
        active_hosts = []
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {executor.submit(check_host_online, ip): ip for ip in ips}
            for future in as_completed(futures):
                res = future.result()
                if res: active_hosts.append(res)
        return active_hosts

    def scan(self) -> List[dict]:
        ip_prefix, nmap_range, ips_to_check, _, _ = get_local_ip_and_range()
        
        if FORCE_STATIC_RANGE:
            return self._check_ssh_ports_in_parallel(ips_to_check)

        # Estratégia 1: Nmap (Método Primário e mais rápido)
        self.logger.info(f"Tentando descoberta com Nmap no range {nmap_range}...")
        nmap_results = discover_ips_with_nmap(nmap_range)
        if nmap_results and len(nmap_results) > 0:
            return sorted(nmap_results, key=lambda x: ipaddress.ip_address(x['ip']))
        
        # Estratégia 2: Arp-scan (Fallback para rede local se o Nmap falhar)
        self.logger.warning("Nmap não encontrou hosts. Tentando ARP Scan...")
        arp_items = discover_ips_with_arp_scan()
        if arp_items:
            return self._check_ssh_ports_in_parallel([item['ip'] for item in arp_items])

        # Estratégia 3: Fallback Final (Verificação manual IP a IP em paralelo)
        self.logger.warning("Métodos rápidos falharam. Iniciando varredura bruta paralela...")
        return self._check_ssh_ports_in_parallel(ips_to_check)