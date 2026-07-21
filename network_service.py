import os
import socket
import platform
import subprocess
import shutil
import ipaddress
import re
import time
from typing import List, Dict, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Configurações de Rede (Sincronizadas com o Ambiente) ---
FORCE_STATIC_RANGE = os.getenv("FORCE_STATIC_RANGE", "false").lower() == "true"
IP_PREFIX_DEFAULT = os.getenv("IP_PREFIX", "192.168.50.")
IP_START = int(os.getenv("IP_START", "1"))
IP_END = int(os.getenv("IP_END", "254"))
IS_WSL = 'microsoft' in platform.uname().release.lower()
SYSTEM = platform.system()

_NMAP_PATH_CACHE = None

def is_valid_ip(ip: str) -> bool:
    """Valida se a string fornecida é um endereço IP válido."""
    try:
        addr = ipaddress.ip_address(ip.strip())
        return addr.version == 4 and not addr.is_multicast and not addr.is_loopback and not addr.is_link_local
    except ValueError:
        return False

def _get_default_gateway() -> Optional[str]:
    try:
        if IS_WSL:
            # No WSL, tenta pegar o gateway físico do Windows
            return _get_windows_gateway_info('gateway')
            
        if SYSTEM == "Linux":
            result = subprocess.run(['ip', 'route'], capture_output=True, text=True)
            for line in result.stdout.splitlines():
                if line.startswith('default via'):
                    return line.split()[2]
        elif SYSTEM == "Windows":
            return _get_windows_gateway_info('gateway')
    except Exception: pass
    return None

def run_windows_powershell(ps_code: str, timeout: float = 5.0) -> Optional[subprocess.CompletedProcess]:
    """Executa o PowerShell do Windows a partir do WSL (usando /init) ou do Windows nativo."""
    if IS_WSL:
        # Usa o wrapper /init do WSL para ignorar limitações de execução direta PE/EXE no binfmt
        cmd = ["/init", "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoProfile", "-Command", ps_code]
    else:
        cmd = ["powershell.exe", "-NoProfile", "-Command", ps_code]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res
    except Exception:
        return None

def _get_windows_gateway_info(target: str = 'gateway') -> Optional[str]:
    """Busca gateway ou IP da interface no Windows via PowerShell (robusto para WSL e qualquer idioma)."""
    try:
        if target == 'gateway':
            ps_code = "$r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1; if ($r) { $r.NextHop }"
        else:
            ps_code = (
                "$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1; "
                "if ($route) { $ip = (Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 | Select-Object -First 1).IPAddress }; "
                "if (!$ip) { $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^127\\.' -and $_.InterfaceAlias -notmatch 'vEthernet' -and $_.InterfaceAlias -notmatch 'Loopback' } | Sort-Object InterfaceMetric | Select-Object -First 1).IPAddress }; "
                "if ($ip) { $ip }"
            )
        
        result = run_windows_powershell(ps_code, timeout=5)
        if result and result.returncode == 0:
            output = result.stdout.strip()
            if is_valid_ip(output):
                return output
    except Exception: pass
    return None

def _get_windows_all_prefixes() -> List[str]:
    """Coleta os prefixos de todas as interfaces IPv4 físicas do Windows Host."""
    try:
        ps_code = "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^127\\.' -and $_.InterfaceAlias -notmatch 'vEthernet' -and $_.InterfaceAlias -notmatch 'Loopback' -and $_.InterfaceAlias -notmatch 'Topaz' -and $_.IPAddress -notmatch '^169\\.254' } | Select-Object -ExpandProperty IPAddress"
        res = run_windows_powershell(ps_code, timeout=4)
        if res and res.returncode == 0:
            prefixes = []
            for line in res.stdout.splitlines():
                line = line.strip()
                if is_valid_ip(line):
                    p = ".".join(line.split('.')[:-1]) + "."
                    if p not in prefixes:
                        prefixes.append(p)
            return prefixes
    except Exception: pass
    return []

def get_local_ip_and_range(logger) -> tuple:
    """Detecta dinamicamente o IP local e define a faixa de busca."""
    if FORCE_STATIC_RANGE:
        gateway_ip = _get_default_gateway()
        ip_prefix = IP_PREFIX_DEFAULT
        nmap_range = f"{ip_prefix}0/24"
        ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
        return ip_prefix, nmap_range, ips_to_check, None, gateway_ip
    logger.debug("Iniciando detecção dinâmica de IP local.")

    gateway_ip = _get_default_gateway()
    primary_interface_ip = None
    base_ip = None

    if SYSTEM == "Windows" or IS_WSL:
        primary_interface_ip = _get_windows_gateway_info('interface')
        if primary_interface_ip and is_valid_ip(primary_interface_ip) and not primary_interface_ip.startswith('127.'):
            base_ip = primary_interface_ip
            logger.debug(f"IP da interface primária detectado via gateway: {base_ip}")
    
    all_local_ips = []
    try:
        if SYSTEM == "Linux" or IS_WSL:
            res = subprocess.run(['ip', '-4', 'addr', 'show'], capture_output=True, text=True)
            for line in res.stdout.splitlines():
                match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/\d+', line)
                if match:
                    ip_str = match.group(1)
                    if is_valid_ip(ip_str) and not ip_str.startswith('127.'):
                        all_local_ips.append(ip_str)
        elif SYSTEM == "Windows":
            host_name = socket.gethostname()
            all_local_ips.extend(socket.gethostbyname_ex(host_name)[2])
    except Exception as e:
        logger.warning(f"Erro ao coletar todos os IPs locais: {e}")

    if gateway_ip and not base_ip:
        try:
            gateway_network = ipaddress.ip_network(f"{gateway_ip}/24", strict=False)
            for ip_str in all_local_ips:
                try:
                    current_ip = ipaddress.ip_address(ip_str)
                    if current_ip in gateway_network:
                        base_ip = ip_str
                        break
                except ValueError: continue
        except Exception: pass

    if not base_ip and all_local_ips:
        private_networks = [
            ipaddress.ip_network('192.168.0.0/16'),
            ipaddress.ip_network('10.0.0.0/8'),
            ipaddress.ip_network('172.16.0.0/12')
        ]
        for ip_str in all_local_ips:
            try:
                current_ip = ipaddress.ip_address(ip_str)
                if current_ip.is_private and (current_ip in private_networks[0] or current_ip in private_networks[1]):
                    base_ip = ip_str
                    break
            except ValueError: continue

    if base_ip and is_valid_ip(base_ip) and not base_ip.startswith('127.'):
        primary_prefix = ".".join(base_ip.split('.')[:-1]) + "."
        all_prefixes = _get_windows_all_prefixes() if (IS_WSL or SYSTEM == "Windows") else []
        if primary_prefix not in all_prefixes:
            all_prefixes.insert(0, primary_prefix)
        
        aggregated_ips = []
        nmap_ranges = []
        for p in all_prefixes:
            nmap_ranges.append(f"{p}0/24")
            aggregated_ips.extend([f"{p}{i}" for i in range(IP_START, IP_END + 1)])
            
        ip_prefix = primary_prefix
        nmap_range = " ".join(nmap_ranges)
        ips_to_check = aggregated_ips
        logger.info(f"Faixas de rede detectadas: {nmap_range} (IP base: {base_ip})")
        return ip_prefix, nmap_range, ips_to_check, base_ip, gateway_ip

    ip_prefix = IP_PREFIX_DEFAULT
    logger.warning(f"Não foi possível detectar o IP local. Usando faixa padrão: {ip_prefix}0/24")
    return ip_prefix, f"{ip_prefix}0/24", [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)], None, _get_default_gateway()

def _find_windows_nmap() -> str:
    global _NMAP_PATH_CACHE
    if _NMAP_PATH_CACHE: return _NMAP_PATH_CACHE
    
    # 1. Tenta localizar no PATH via PowerShell
    result = run_windows_powershell("Get-Command nmap.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source", timeout=3)
    path = result.stdout.strip() if result else ""
    if not path:
        # 2. Tenta caminhos de instalação padrão
        for p in ["C:\\Program Files (x86)\\Nmap\\nmap.exe", "C:\\Program Files\\Nmap\\nmap.exe"]:
            check_res = run_windows_powershell(f"Test-Path '{p}'", timeout=3)
            if check_res and "True" in check_res.stdout:
                path = p; break
    _NMAP_PATH_CACHE = f'"{path}"' if path else "nmap"
    return _NMAP_PATH_CACHE

def detect_os_from_ssh_banner(banner: str) -> str:
    """Classifica o sistema operacional a partir do cabeçalho (banner) do serviço SSH."""
    if not banner:
        return 'unknown'
    b_lower = banner.lower()
    if 'ubuntu' in b_lower:
        return 'ubuntu'
    if 'mint' in b_lower:
        return 'mint'
    if 'debian' in b_lower:
        return 'debian'
    if 'windows' in b_lower or 'win32' in b_lower or 'microsoft' in b_lower:
        return 'windows'
    if 'freebsd' in b_lower or 'openbsd' in b_lower:
        return 'linux'
    if 'openssh' in b_lower or 'linux' in b_lower:
        return 'linux'
    return 'unknown'

def probe_ssh_banner(ip: str, timeout: float = 0.5) -> Tuple[bool, Optional[str]]:
    """Tenta conectar na porta 22 e capturar o banner do SSH servidor."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        if sock.connect_ex((ip, 22)) == 0:
            try:
                # Tenta ler a mensagem inicial de identificação do SSH (ex: SSH-2.0-OpenSSH...)
                data = sock.recv(1024)
                if data:
                    banner_str = data.decode('utf-8', errors='ignore').strip()
                    return True, banner_str
            except Exception:
                pass
            return True, None
    except Exception:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return False, None

def probe_tcp_port(ip: str, port: int, timeout: float = 0.3) -> bool:
    """Verifica rapidamente se uma porta TCP específica está aberta."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        res = sock.connect_ex((ip, port))
        return res == 0
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass

def ping_host_get_ttl(ip: str, timeout_ms: int = 400) -> Tuple[bool, Optional[int]]:
    """Envia um ping rápido e extrai o valor de TTL (Time To Live)."""
    try:
        is_windows = SYSTEM == 'Windows'
        timeout_sec = max(0.2, timeout_ms / 1000.0)
        cmd = ['ping', '-n' if is_windows else '-c', '1', '-W' if not is_windows else '-w', f"{timeout_sec}" if not is_windows else f"{timeout_ms}", ip]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0:
            out = res.stdout
            ttl_match = re.search(r'ttl[=\s](\d+)', out, re.IGNORECASE)
            ttl = int(ttl_match.group(1)) if ttl_match else None
            return True, ttl
    except Exception:
        pass
    return False, None

def detect_os_fingerprint(ip: str, ssh_banner: Optional[str] = None, ttl: Optional[int] = None) -> str:
    """Determina o SO aproximado combinando SSH Banner, TTL do Ping e portas típicas."""
    # 1. Análise do Banner SSH (Maior precisão para distribuições Linux e Windows OpenSSH)
    if ssh_banner:
        detected = detect_os_from_ssh_banner(ssh_banner)
        if detected != 'unknown':
            return detected

    # 2. Análise por portas de rede do Windows (Porta 135 - RPC ou 445 - SMB)
    if probe_tcp_port(ip, 135, timeout=0.25) or probe_tcp_port(ip, 445, timeout=0.25):
        return 'windows'

    # 3. Análise pelo valor de TTL
    # TTL ~128 -> Windows (padrão 128)
    # TTL ~64 -> Linux/Unix (padrão 64)
    if ttl is not None:
        if 100 <= ttl <= 135:
            return 'windows'
        elif 40 <= ttl <= 70:
            return 'linux'

    # 4. Se tiver SSH mas não identificou distro específica -> Linux
    if ssh_banner is not None:
        return 'linux'

    return 'unknown'

def check_host_online(ip: str) -> Optional[dict]:
    """Verifica se um host está online via SSH (porta 22) ou SMB (porta 445) com detecção de SO."""
    # 1. Teste primário da porta 22 (SSH) com leitura de banner
    is_ssh, banner = probe_ssh_banner(ip, timeout=0.35)
    if is_ssh:
        os_type = detect_os_fingerprint(ip, ssh_banner=banner)
        return {'ip': ip, 'type': 'ssh', 'os_type': os_type, 'ssh_banner': banner}

    # 2. Teste da porta 445 (SMB Windows)
    if probe_tcp_port(ip, 445, timeout=0.2):
        return {'ip': ip, 'type': 'ping', 'os_type': 'windows'}

    return None

def discover_ips_with_nmap(ip_range: str, logger) -> Optional[List[dict]]:
    """Executa o nmap para descobrir hosts ativos, priorizando a versão nativa do sistema."""
    nmap_path = _find_nmap_path()
    if IS_WSL and (not nmap_path or nmap_path.endswith('.exe')):
        nmap_exe = _find_windows_nmap()
        ps_code = f"& {nmap_exe} -p 22 --open -n -T4 --max-rtt-timeout 250ms --min-parallelism 100 --min-hostgroup 64 --host-timeout 3s -oG - {ip_range}"
        command = ["/init", "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoProfile", "-Command", ps_code]
    elif nmap_path:
        command = [nmap_path, "-p", "22", "--open", "-n", "-T4", "--max-rtt-timeout", "250ms", "--min-parallelism", "100", "--min-hostgroup", "64", "--host-timeout", "3s", "-oG", "-", ip_range]
    else:
        return None

    try:
        logger.debug(f"Executando Nmap com comando: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, errors='replace')
        logger.debug(f"Nmap stdout: {result.stdout}")
        logger.debug(f"Nmap stderr: {result.stderr}")

        active_hosts_data = {} # Usamos dicionário para armazenar IP -> {'type': ..., 'mac': ...}
        for line in result.stdout.splitlines():
            if "Host:" not in line: continue
            
            # Regex para extrair IP e MAC
            match = re.search(r'Host: (\d+\.\d+\.\d+\.\d+).*?MAC: (([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2})', line)
            ip = None
            mac = None
            if match:
                ip = match.group(1)
                mac = match.group(2).replace('-', ':').lower()
            else:
                # Fallback para IPs sem MAC na linha (ainda precisamos do IP)
                ip_match = re.search(r'Host: (\d+\.\d+\.\d+\.\d+)', line)
                if ip_match:
                    ip = ip_match.group(1)

            if not ip: continue 

            host_entry = active_hosts_data.get(ip, {'type': 'ping', 'mac': None})
            if "/open/tcp" in line: host_entry['type'] = 'ssh'
            if mac and not host_entry['mac']: host_entry['mac'] = mac
            
            active_hosts_data[ip] = host_entry
        
        return [{'ip': ip, 'type': data['type'], 'mac': data['mac']} for ip, data in active_hosts_data.items()]
    except Exception as e:
        logger.error(f"Erro ao executar ou parsear Nmap: {e}", exc_info=True)
        return None


def discover_ips_with_arp_scan(interface: Optional[str] = None) -> Optional[List[dict]]:
    """Varredura proativa via ARP. No WSL, isso captura apenas a rede virtual."""
    try:
        command = ["sudo", "arp-scan", "--localnet", "--numeric", "--quiet", "--retry=3", "--timeout=500"]
        if interface:
            command.extend(["-I", interface])
            
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        active_hosts = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and is_valid_ip(parts[0]):
                active_hosts.append({
                    'ip': parts[0], 
                    'mac': parts[1].replace('-', ':').lower(),
                    'type': 'ping'
                })
        return active_hosts
    except Exception: return None

def get_windows_arp_table() -> List[dict]:
    """Coleta a tabela ARP do Windows Host via PowerShell (essencial para WSL)."""
    if not IS_WSL and SYSTEM != "Windows":
        return []
    try:
        ps_code = "Get-NetNeighbor -AddressFamily IPv4 | Select-Object IPAddress, LinkLayerAddress | ConvertTo-Json"
        result = run_windows_powershell(ps_code, timeout=5)
        if result and result.returncode == 0 and result.stdout.strip():
            import json
            data = json.loads(result.stdout)
            if isinstance(data, dict): data = [data]
            
            return [{
                'ip': item.get('IPAddress'),
                'mac': item.get('LinkLayerAddress').replace('-', ':').lower() if item.get('LinkLayerAddress') else None
            } for item in data if item.get('IPAddress') and item.get('LinkLayerAddress')]
    except Exception:
        pass
    return []


class NetworkScanner:
    def __init__(self, logger):
        self.logger = logger

    def _check_ssh_ports_in_parallel(self, ips: List[str]) -> List[dict]:
        active_hosts = []
        unique_ips = sorted(list(set(ips)), key=lambda x: ipaddress.ip_address(x))
        with ThreadPoolExecutor(max_workers=min(32, max(8, len(unique_ips)))) as executor:
            futures = {executor.submit(check_host_online, ip): ip for ip in unique_ips}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    active_hosts.append(res)
        return active_hosts

    def _enrich_results_with_os_type(self, results: List[dict]) -> List[dict]:
        """Enriquece a lista de resultados de varredura com a detecção de SO via Fingerprint em paralelo."""
        if not results:
            return []

        def probe_os(host):
            ip = host.get('ip')
            if not ip:
                return host
            if 'os_type' not in host or host['os_type'] == 'unknown':
                is_ssh, banner = probe_ssh_banner(ip, timeout=0.35)
                if is_ssh:
                    host['type'] = 'ssh'
                    host['os_type'] = detect_os_fingerprint(ip, ssh_banner=banner)
                else:
                    host['os_type'] = 'linux' if host.get('type') == 'ssh' else 'windows'
            return host

        with ThreadPoolExecutor(max_workers=min(32, max(8, len(results)))) as executor:
            enriched = list(executor.map(probe_os, results))
        return enriched

    def scan(self, custom_range: Optional[str] = None) -> List[dict]:
        # Obtém dados da detecção automática inicial
        ip_prefix, nmap_range, ips_to_check, _, _ = get_local_ip_and_range(self.logger)

        if custom_range:
            try:
                parts = [p.strip() for p in custom_range.split(',')]
                aggregated_ips = []
                nmap_targets = []

                for part in parts:
                    if not part: continue
                    
                    match_local = re.match(r'^(\d+)\s*(?:-|a|to)\s*(\d+)$', part)
                    match_short = re.match(r'^(\d+\.\d+\.\d+\.)(\d+)\s*(?:-|a|to)\s*(\d+)$', part)
                    match_full = re.match(r'^(\d+\.\d+\.\d+\.\d+)\s*(?:-|a|to)\s*(\d+\.\d+\.\d+\.\d+)$', part)

                    if match_local:
                        start, end = int(match_local.group(1)), int(match_local.group(2))
                        if start > end: start, end = end, start
                        nmap_targets.append(f"{ip_prefix}{start}-{end}")
                        aggregated_ips.extend([f"{ip_prefix}{i}" for i in range(start, end + 1)])
                    
                    elif match_short:
                        prefix = match_short.group(1)
                        start, end = int(match_short.group(2)), int(match_short.group(3))
                        if start > end: start, end = end, start
                        nmap_targets.append(f"{prefix}{start}-{end}")
                        aggregated_ips.extend([f"{prefix}{i}" for i in range(start, end + 1)])
                        
                    elif match_full:
                        ip_s = ipaddress.IPv4Address(match_full.group(1))
                        ip_e = ipaddress.IPv4Address(match_full.group(2))
                        if ip_s > ip_e: ip_s, ip_e = ip_e, ip_s
                        aggregated_ips.extend([str(ipaddress.IPv4Address(i)) for i in range(int(ip_s), int(ip_e) + 1)])
                        
                        s_parts, e_parts = str(ip_s).split('.'), str(ip_e).split('.')
                        if s_parts[:-1] == e_parts[:-1]:
                            nmap_targets.append(f"{'.'.join(s_parts[:-1])}.{s_parts[-1]}-{e_parts[-1]}")
                        else:
                            nmap_targets.append(f"{ip_s}-{ip_e}")
                    
                    else:
                        sanitized = part.replace('x', '0/24')
                        try:
                            net = ipaddress.ip_network(sanitized, strict=False)
                            nmap_targets.append(str(net))
                            aggregated_ips.extend([str(ip) for ip in net.hosts()])
                        except:
                            if is_valid_ip(part):
                                nmap_targets.append(part)
                                aggregated_ips.append(part)

                ips_to_check = sorted(list(set(aggregated_ips)), key=lambda x: ipaddress.ip_address(x))
                nmap_range = " ".join(nmap_targets)
                self.logger.info(f"Scanner: Usando faixa customizada: {nmap_range}")
            except Exception as e:
                self.logger.error(f"Erro ao processar faixa '{custom_range}': {e}. Usando detecção automática.")

        if FORCE_STATIC_RANGE:
            res = self._check_ssh_ports_in_parallel(ips_to_check)
            return sorted(res, key=lambda x: ipaddress.ip_address(x['ip']))

        # Estratégia 1: Sondagem Paralela de Soquetes Ultra-Rápida + Tabela ARP (Sub-segundos)
        self.logger.info("Iniciando varredura paralela ultra-rápida por soquetes...")
        win_arp = get_windows_arp_table()
        arp_items = discover_ips_with_arp_scan() or []
        
        known_ips = set()
        candidate_ips = list(ips_to_check)

        if win_arp:
            for item in win_arp:
                if item['ip'] not in known_ips and is_valid_ip(item['ip']) and not item['ip'].startswith('127.'):
                    known_ips.add(item['ip'])
                    if item['ip'] not in candidate_ips:
                        candidate_ips.append(item['ip'])

        if arp_items:
            for item in arp_items:
                if item['ip'] not in known_ips and is_valid_ip(item['ip']) and not item['ip'].startswith('127.'):
                    known_ips.add(item['ip'])
                    if item['ip'] not in candidate_ips:
                        candidate_ips.append(item['ip'])

        res = self._check_ssh_ports_in_parallel(candidate_ips)
        if res and len(res) > 0:
            return sorted(res, key=lambda x: ipaddress.ip_address(x['ip']))

        # Estratégia 2: Nmap (Fallback)
        self.logger.info(f"Tentando descoberta com Nmap no range {nmap_range}...")
        nmap_results = discover_ips_with_nmap(nmap_range, self.logger)
        if nmap_results and len(nmap_results) > 0:
            enriched = self._enrich_results_with_os_type(nmap_results)
            return sorted(enriched, key=lambda x: ipaddress.ip_address(x['ip']))

        return []

def send_wake_on_lan(mac_address: str, logger: Any = None) -> bool:
    """Envia um 'Magic Packet' para o endereço MAC especificado."""
    try:
        # Sanitiza o MAC: remove :, - e espaços
        mac_clean = re.sub(r'[^a-fA-F0-9]', '', mac_address)
        if len(mac_clean) != 12:
            return False
            
        if IS_WSL:
            # No WSL, usamos PowerShell para disparar broadcasts em múltiplas portas e destinos.
            # Isso replica o comportamento do Veyon, enviando para o broadcast global e o direcionado da sub-rede.
            ps_cmd = (
                f"$m='{mac_clean}';$p=[byte[]](,0xFF*6);"
                f"$h=for($i=0;$i -lt $m.Length;$i+=2){{[byte]('0x'+$m.Substring($i,2))}};"
                f"for($i=0;$i -lt 16;$i++){{$p+=$h}};"
                f"$u=New-Object System.Net.Sockets.UdpClient;$u.EnableBroadcast=$true;"
                f"$t=@('255.255.255.255');"
                f"Get-NetIPAddress -AddressFamily IPv4 | Where-Object {{$_.InterfaceAlias -notmatch 'vEthernet|Loopback'}} | ForEach-Object {{ $t += $_.IPAddress -replace '\\.\\d+$', '.255' }};"
                f"$dests = $t | Select-Object -Unique; "
                f"Write-Output \"Alvos WoL detectados: $($dests -join ', ')\"; "
                f"foreach($dest in $dests){{ "
                f"  try {{ [void]$u.Send($p,$p.Length,$dest,9); [void]$u.Send($p,$p.Length,$dest,7) }} catch {{}} "
                f"}};"
                f"$u.Close()"
            )
            result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps_cmd], 
                           capture_output=True, text=True, errors='replace', check=True, timeout=5)
            if logger and result.stdout:
                logger.info(f"[WoL Debug] {result.stdout.strip()}")
        else:
            # Implementação nativa em Python para Linux real
            mac_bytes = bytes.fromhex(mac_clean)
            magic_packet = b'\xff' * 6 + mac_bytes * 16
            
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                # Tenta enviar para o broadcast geral e limitado
                try:
                    s.sendto(magic_packet, ('<broadcast>', 9))
                except Exception: pass
                s.sendto(magic_packet, ('255.255.255.255', 9))
            
        return True
    except Exception:
        return False