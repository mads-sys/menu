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
IP_PREFIX_DEFAULT = os.getenv("IP_PREFIX", "192.168.1.")
IP_START = 1
IP_END = 254
IS_WSL = 'microsoft' in platform.uname().release.lower()

_NMAP_PATH_CACHE = None

def is_valid_ip(ip: str) -> bool:
    """Valida se a string fornecida é um endereço IP válido."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def _get_default_gateway() -> Optional[str]:
    system = platform.system()
    try:
        if system == "Linux":
            result = subprocess.run(['ip', 'route'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if line.startswith('default via'):
                    return line.split()[2]
        elif system == "Windows":
            result = subprocess.run(['route', 'print', '0.0.0.0'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if line.strip().startswith('0.0.0.0'):
                    parts = line.split()
                    if len(parts) >= 3:
                        return parts[2]
    except Exception: pass
    return None

def _get_windows_host_ip() -> Optional[str]:
    try:
        result = subprocess.run(['route.exe', 'print', '0.0.0.0'], capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if line.strip().startswith('0.0.0.0'):
                parts = line.split()
                if len(parts) >= 4:
                    ip = parts[3]
                    if is_valid_ip(ip) and not ip.startswith('127.'):
                        return ip
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
        base_ip = _get_windows_host_ip()
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
    ps_command = 'Get-Command nmap.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source'
    result = subprocess.run(["powershell.exe", "-Command", ps_command], capture_output=True, text=True)
    found_path = result.stdout.strip()
    _NMAP_PATH_CACHE = f'"{found_path}"' if found_path else "nmap"
    return _NMAP_PATH_CACHE

def check_host_online(ip: str) -> Optional[dict]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)
    try:
        if sock.connect_ex((ip, 22)) == 0:
            return {'ip': ip, 'type': 'ssh'}
    except Exception: pass
    finally: sock.close()
    return None

def discover_ips_with_nmap(ip_range: str) -> Optional[List[dict]]:
    try:
        encoding = 'cp850' if IS_WSL else 'utf-8'
        if IS_WSL:
            nmap_exe = _find_windows_nmap()
            command = ["powershell.exe", "-Command", f"& {nmap_exe} -p 22 -T4 -Pn --open -oG - {ip_range}"]
        else:
            command = ["nmap", "-p", "22", "-T4", "-Pn", "--open", "-oG", "-", ip_range]

        result = subprocess.run(command, capture_output=True, text=True, timeout=60, encoding=encoding)
        active_ips = []
        for line in result.stdout.splitlines():
            if "Host:" in line and "/open/tcp" in line:
                parts = line.split()
                if len(parts) > 1:
                    active_ips.append({'ip': parts[1], 'type': 'ssh'})
        return active_ips
    except Exception: return None

def discover_ips_with_arp_scan() -> Optional[List[dict]]:
    if IS_WSL: return None
    try:
        command = ["sudo", "arp-scan", "--localnet", "--numeric", "--quiet"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        active_ips = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].count('.') == 3:
                active_ips.append({'ip': parts[0], 'type': 'ssh', 'mac': parts[1]})
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

        nmap_results = discover_ips_with_nmap(nmap_range)
        if nmap_results: return nmap_results
        
        arp_results = discover_ips_with_arp_scan()
        if arp_results:
            return self._check_ssh_ports_in_parallel([item['ip'] for item in arp_results])

        return self._check_ssh_ports_in_parallel(ips_to_check)