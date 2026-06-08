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

def _get_windows_gateway_info(target: str = 'gateway') -> Optional[str]:
    """Busca gateway ou IP da interface no Windows via PowerShell (robusto para WSL e qualquer idioma)."""
    try:
        if target == 'gateway':
            # Pega o Gateway da rota padrão (0.0.0.0)
            cmd = ["powershell.exe", "-Command", "$r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1; if ($r) { $r.NextHop }"]
        else:
            # Pega o IP da interface física real, ignorando adaptadores virtuais do WSL e Loopback.
            # Isso é essencial para "olhar por trás" do WSL e achar a rede do laboratório.
            cmd = ["powershell.exe", "-Command",
                   "$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1; "
                   "if ($route) { $ip = (Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 | Select-Object -First 1).IPAddress }; "
                   "if (!$ip) { $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^127\\.' -and $_.InterfaceAlias -notmatch 'vEthernet' -and $_.InterfaceAlias -notmatch 'Loopback' } | Sort-Object InterfaceMetric | Select-Object -First 1).IPAddress }; "
                   "if ($ip) { $ip }"]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        output = result.stdout.strip()
        if is_valid_ip(output):
            return output
    except Exception: pass
    return None

def get_local_ip_and_range(logger) -> tuple:
    """Detecta dinamicamente o IP local e define a faixa de busca."""
    if FORCE_STATIC_RANGE:
        gateway_ip = _get_default_gateway()
        # server_ip is not used in this branch, so it can be None
        ip_prefix = IP_PREFIX_DEFAULT
        nmap_range = f"{ip_prefix}0/24"
        ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
        return ip_prefix, nmap_range, ips_to_check, None, gateway_ip
    logger.debug("Iniciando detecção dinâmica de IP local.")

    gateway_ip = _get_default_gateway()
    primary_interface_ip = None # New variable to store the IP of the primary interface
    base_ip = None

    # Estratégia 1: Tenta detectar o IP local via conexão externa (8.8.8.8).
    # No WSL, pulamos esta etapa porque ela retorna o IP da rede virtual (172.x).
    if not IS_WSL:
        logger.debug("Tentando detectar IP local via conexão externa (8.8.8.8)...")
        try:
            with socket.create_connection(("8.8.8.8", 80), timeout=2) as s:
                detected_ip = s.getsockname()[0]
                if is_valid_ip(detected_ip) and not detected_ip.startswith('127.'):
                    base_ip = detected_ip
                    logger.debug(f"IP local detectado via 8.8.8.8: {base_ip}")
        except Exception:
            logger.debug("Falha ao detectar IP local via 8.8.8.8.")

    # Estratégia 1.5: Se em Windows ou WSL, tenta obter o IP da interface física do Windows.
    # Esta é a fonte mais confiável para o IP da interface principal em ambientes com NAT/VIRTUAL.
    if SYSTEM == "Windows" or IS_WSL:
        primary_interface_ip = _get_windows_gateway_info('interface')
        if primary_interface_ip and is_valid_ip(primary_interface_ip) and not primary_interface_ip.startswith('127.'):
            base_ip = primary_interface_ip # Prioriza o IP do Host (Windows) em vez do IP interno do WSL
            logger.debug(f"IP da interface primária detectado via gateway: {base_ip}")
    
    # Collect all local IPs from various sources
    all_local_ips = []
    try:
        if SYSTEM == "Linux" or IS_WSL:
            # Use 'ip -4 addr show' for more comprehensive and structured IP info on Linux/WSL
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

    # Estratégia 2: Prioriza encontrar um IP na mesma sub-rede do gateway (se base_ip ainda não foi definido ou se o IP da interface primária não foi definido)
    if gateway_ip:
        logger.debug(f"Gateway detectado: {gateway_ip}. Tentando encontrar IP local na mesma rede.")
        try:
            gateway_network = ipaddress.ip_network(f"{gateway_ip}/24", strict=False) # Assume /24 for simplicity
            for ip_str in all_local_ips:
                try:
                    current_ip = ipaddress.ip_address(ip_str)
                    if current_ip in gateway_network:
                        base_ip = ip_str # Pode sobrescrever o base_ip se o 8.8.8.8 retornou algo estranho
                        logger.debug(f"IP local encontrado na mesma rede do gateway: {base_ip}")
                        break
                except ValueError:
                    continue
        except Exception as e:
            logger.warning(f"Erro ao processar rede do gateway: {e}")
        
        if not base_ip:
            logger.warning(f"Nenhum IP local encontrado na mesma rede do gateway {gateway_ip}. Tentando outras formas.")

    # Estratégia 3: Iterar pelos IPs coletados, priorizando faixas privadas comuns (se base_ip ainda não foi definido)
    if not base_ip and all_local_ips:
        logger.debug("Tentando detectar IP local a partir de IPs coletados, priorizando redes privadas.")
        
        private_networks = [
            ipaddress.ip_network('192.168.0.0/16'),
            ipaddress.ip_network('10.0.0.0/8'),
            ipaddress.ip_network('172.16.0.0/12')
        ]

        # Prioriza 192.168.x.x ou 10.x.x.x
        for ip_str in all_local_ips:
            try:
                current_ip = ipaddress.ip_address(ip_str)
                if current_ip.is_private and (current_ip in private_networks[0] or current_ip in private_networks[1]):
                    base_ip = ip_str
                    logger.debug(f"IP local detectado (prioridade privada 192.168/10): {base_ip}")
                    break
            except ValueError:
                continue
        
        # Em seguida, 172.16.x.x - 172.31.x.x
        if not base_ip:
            for ip_str in all_local_ips:
                try:
                    current_ip = ipaddress.ip_address(ip_str)
                    if current_ip.is_private and current_ip in private_networks[2]:
                        base_ip = ip_str
                        logger.debug(f"IP local detectado (prioridade privada 172.16-31): {base_ip}")
                        break
                except ValueError:
                    continue

    # Estratégia 4: Última tentativa usando socket.gethostbyname ou qualquer IP válido não-loopback/link-local (se base_ip ainda não foi definido)
    if not base_ip:
        logger.debug("Nenhum IP privado prioritário encontrado. Tentando socket.gethostbyname ou qualquer IP válido.")
        for ip_str in all_local_ips:
            try:
                current_ip = ipaddress.ip_address(ip_str)
                if not current_ip.is_loopback and not current_ip.is_link_local:
                    base_ip = ip_str
                    logger.debug(f"IP local detectado (qualquer válido não-loopback/link-local): {base_ip}")
                    break
            except ValueError:
                continue
        if not base_ip:
            try:
                base_ip = socket.gethostbyname(socket.gethostname())
                if base_ip and is_valid_ip(base_ip) and not base_ip.startswith('127.'):
                    logger.debug(f"IP local detectado via gethostbyname: {base_ip}")
                else:
                    base_ip = None
            except Exception:
                logger.error("Falha total ao detectar IP local.")
                base_ip = None

    if base_ip and is_valid_ip(base_ip) and not base_ip.startswith('127.'):
        ip_prefix = ".".join(base_ip.split('.')[:-1]) + "."
        nmap_range = f"{ip_prefix}0/24"
        ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
        logger.info(f"Faixa de rede detectada: {ip_prefix}0/24 (IP base: {base_ip})")
        return ip_prefix, nmap_range, ips_to_check, base_ip, gateway_ip

    ip_prefix = IP_PREFIX_DEFAULT
    logger.warning(f"Não foi possível detectar o IP local. Usando faixa padrão: {ip_prefix}0/24")
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
    sock.settimeout(0.8) # Reduzido para 0.8s para varredura mais rápida em LAN
    try:
        if sock.connect_ex((ip, 22)) == 0:
            return {'ip': ip, 'type': 'ssh'}
    except Exception: pass
    finally: sock.close()

    # Fallback: Tenta Ping se o SSH falhou
    try:
        is_windows = SYSTEM == 'Windows'
        # Timeout reduzido para 500ms para maior agilidade em redes locais
        cmd = ['ping', '-n' if is_windows else '-c', '1', '-W' if not is_windows else '-w', '0.5' if not is_windows else '500', ip]
        if subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3) == 0:
            return {'ip': ip, 'type': 'ping'}
    except: pass
    
    return None

def discover_ips_with_nmap(ip_range: str, logger) -> Optional[List[dict]]:
    """Executa o nmap para descobrir hosts ativos, priorizando a versão nativa do sistema."""
    try:
        # Tenta usar o nmap local (Linux ou WSL nativo) primeiro.
        # Isso evita os problemas de encoding e pipes do PowerShell/Windows Nmap.
        nmap_path = shutil.which("nmap")
        
        if IS_WSL and (not nmap_path or nmap_path.endswith('.exe')):
            # Se estiver no WSL e NÃO houver nmap no Linux, tenta a chamada via PowerShell
            nmap_exe = _find_windows_nmap()
            # Adicionamos --min-parallelism e --host-timeout para acelerar a varredura em redes rápidas
            command = ["powershell.exe", "-NoProfile", "-Command", f"& {nmap_exe} -p 22 --open -n -T4 --max-rtt-timeout 500ms --min-parallelism 100 --min-hostgroup 64 --host-timeout 60s -oG - {ip_range}"]
        elif nmap_path:
            command = [nmap_path, "-p", "22", "--open", "-n", "-T4", "--max-rtt-timeout", "500ms", "--min-parallelism", "100", "--min-hostgroup", "64", "--host-timeout", "60s", "-oG", "-", ip_range]
        else:
            return None

        logger.debug(f"Executando Nmap com comando: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, errors='replace')
        logger.debug(f"Nmap stdout: {result.stdout}")
        logger.debug(f"Nmap stderr: {result.stderr}")

        active_hosts_data = {} # Usamos dicionário para armazenar IP -> {'type': ..., 'mac': ...}
        for line in result.stdout.splitlines():
            if "Host:" not in line: continue
            
            # Regex para extrair IP e MAC
            # Nmap -oG output format: Host: <IP> (<hostname>)   Ports: ...   MAC: <MAC> (<Vendor>)
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

            if not ip: continue # Se não achou IP, pula a linha

            # Initialize with default values if not present
            host_entry = active_hosts_data.get(ip, {'type': 'ping', 'mac': None})

            if "/open/tcp" in line: host_entry['type'] = 'ssh'
            if mac and not host_entry['mac']: host_entry['mac'] = mac # Only update if MAC is found and not already set
            
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
        # Comando PowerShell que retorna IP e MAC em formato JSON
        cmd = ["powershell.exe", "-NoProfile", "-Command", 
               "Get-NetNeighbor -AddressFamily IPv4 | Select-Object IPAddress, LinkLayerAddress | ConvertTo-Json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            import json
            data = json.loads(result.stdout)
            if isinstance(data, dict): data = [data] # Garante que seja lista
            
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
        # Aumento de workers para cobrir sub-redes inteiras rapidamente
        with ThreadPoolExecutor(max_workers=255) as executor:
            futures = {executor.submit(check_host_online, ip): ip for ip in ips}
            for future in as_completed(futures):
                res = future.result()
                if res: active_hosts.append(res)
        return active_hosts

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
                    
                    # 1. Regex para intervalo curto local: "50 a 80" ou "50-80"
                    match_local = re.match(r'^(\d+)\s*(?:-|a|to)\s*(\d+)$', part)
                    # 2. Regex para intervalo curto com prefixo: "192.168.1.50 a 80"
                    match_short = re.match(r'^(\d+\.\d+\.\d+\.)(\d+)\s*(?:-|a|to)\s*(\d+)$', part)
                    # 3. Regex para intervalo completo: "10.0.0.1 to 10.0.0.10"
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
                        # Fallback: CIDR ou IP único (ex: 192.168.1.x ou 10.0.0.0/24)
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
            return self._check_ssh_ports_in_parallel(ips_to_check)

        # Estratégia 1: Nmap (Método Primário e mais rápido)
        self.logger.info(f"Tentando descoberta com Nmap no range {nmap_range}...")
        nmap_results = discover_ips_with_nmap(nmap_range, self.logger)
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

def send_wake_on_lan(mac_address: str) -> bool:
    """Envia um 'Magic Packet' para o endereço MAC especificado."""
    try:
        # Sanitiza o MAC: remove :, - e espaços
        mac_clean = re.sub(r'[^a-fA-F0-9]', '', mac_address)
        if len(mac_clean) != 12:
            return False
            
        # Converte para bytes
        mac_bytes = bytes.fromhex(mac_clean)
        
        # Constrói o Magic Packet (6x FF + 16x MAC)
        magic_packet = b'\xff' * 6 + mac_bytes * 16
        
        # Envia via Broadcast UDP (porta 9)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(magic_packet, ('<broadcast>', 9))
            s.sendto(magic_packet, ('255.255.255.255', 9))
            
        return True
    except Exception:
        return False