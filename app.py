import os
import platform
import subprocess
import socket
import ipaddress
import threading
import re
import shlex
import time
from datetime import datetime
import webbrowser
import signal
from typing import Dict, Optional, Any, Tuple
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from multiprocessing import Pool, cpu_count
import json
import binascii
import socketserver
import select

from flask import Flask, jsonify, request, send_from_directory, Response, Blueprint

import paramiko
from flask_cors import CORS
from waitress import serve

# --- Importações dos Módulos de Serviço Refatorados ---
from command_builder import COMMANDS, _get_command_builder, CommandExecutionError, _parse_system_info
from ssh_service import ssh_connect, _handle_ssh_exception, _execute_for_each_user, _execute_shell_command, _stream_shell_command, list_sftp_backups, _handle_cleanup_wallpaper

# --- Configuração da Aplicação Flask ---
app = Flask(__name__)
# Permite requisições de diferentes origens (front-end)
CORS(app)

# Define o diretório raiz para servir arquivos estáticos (frontend)
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# --- Configuração da Faixa de IPs ---
# Para forçar a busca na faixa estática abaixo, defina FORCE_STATIC_RANGE como True.
FORCE_STATIC_RANGE = False
# Define uma faixa de IPs estática para a busca.
IP_PREFIX = "192.168.0."
IP_START = 1
IP_END = 254
# Lista de IPs a serem sempre excluídos dos resultados da busca (ex: gateway, servidor).
# Adicione aqui os IPs que você não quer que apareçam na lista.
IP_EXCLUSION_LIST = ["192.168.0.1", "192.168.1.1"]


# --- Configurações Lidas do Ambiente (com valores padrão) ---
SSH_USER = os.getenv("SSH_USER", "aluno") # Usuário padrão para conexão, que deve ter privilégios sudo.
NOVNC_DIR = 'novnc' # Caminho relativo para o Blueprint

# --- Gerenciamento de Processos e Portas ---
vnc_processes: Dict[str, Dict[str, Any]] = {}
vnc_lock = threading.Lock() # Lock para garantir thread-safety no dicionário vnc_processes
BACKUP_ROOT_DIR = "atalhos_desativados"
KNOWN_MACS_FILE = os.path.join(APP_ROOT, 'known_macs.json')
IP_BLOCKLIST_FILE = os.path.join(APP_ROOT, 'ip_blocklist.json') # Novo
known_macs = {}
ip_blocklist = set() # Novo, usa um set para performance

def load_known_macs():
    """Carrega o cache de endereços MAC do disco."""
    global known_macs
    if os.path.exists(KNOWN_MACS_FILE):
        try:
            with open(KNOWN_MACS_FILE, 'r') as f:
                known_macs = json.load(f)
        except Exception as e:
            app.logger.error(f"Erro ao carregar MACs conhecidos: {e}")

def save_known_macs():
    """Salva o cache de endereços MAC no disco."""
    try:
        with open(KNOWN_MACS_FILE, 'w') as f:
            json.dump(known_macs, f)
    except Exception as e:
        app.logger.error(f"Erro ao salvar MACs conhecidos: {e}")

# Novas funções para a blocklist
def load_ip_blocklist():
    """Carrega a lista de IPs bloqueados do disco."""
    global ip_blocklist
    if os.path.exists(IP_BLOCKLIST_FILE):
        try:
            with open(IP_BLOCKLIST_FILE, 'r') as f:
                ip_blocklist = set(json.load(f))
        except Exception as e:
            app.logger.error(f"Erro ao carregar a blocklist de IPs: {e}")

def save_ip_blocklist():
    """Salva a lista de IPs bloqueados no disco."""
    try:
        with open(IP_BLOCKLIST_FILE, 'w') as f:
            json.dump(list(ip_blocklist), f, indent=4)
    except Exception as e:
        app.logger.error(f"Erro ao salvar a blocklist de IPs: {e}")

# Carrega os MACs ao iniciar
try:
    load_known_macs()
    load_ip_blocklist() # Carrega a blocklist ao iniciar
except Exception as e:
    print(f"ERRO NA INICIALIZAÇÃO: {e}")

def is_valid_ip(ip: str) -> bool:
    """Valida se a string fornecida é um endereço IP válido."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def _harvest_macs_from_arp():
    """Lê a tabela ARP do sistema para atualizar o cache de MACs."""
    global known_macs
    updated = False

    if IS_WSL:
        try:
            # No WSL, a tabela ARP interna (/proc/net/arp) vê apenas o switch virtual.
            # Precisamos consultar a tabela ARP do host Windows via arp.exe.
            result = subprocess.run(['arp.exe', '-a'], capture_output=True, text=True, errors='ignore')
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    ip_candidate = parts[0]
                    mac_candidate = parts[1]
                    # Valida IP e MAC (formato Windows usa hífens: 00-11-22...)
                    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip_candidate) and re.match(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$", mac_candidate):
                        mac_normalized = mac_candidate.replace('-', ':').lower()
                        if mac_normalized != "ff:ff:ff:ff:ff:ff" and not ip_candidate.endswith('.255') and not ip_candidate.startswith('224.') and known_macs.get(ip_candidate) != mac_normalized:
                            known_macs[ip_candidate] = mac_normalized
                            updated = True
        except Exception as e:
            app.logger.warning(f"Falha ao ler tabela ARP do Windows: {e}")

    try:
        # Tenta ler /proc/net/arp (Linux/WSL)
        if os.path.exists('/proc/net/arp'):
            with open('/proc/net/arp', 'r') as f:
                next(f) # Pula o cabeçalho
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip = parts[0]
                        mac = parts[3]
                        if mac != "00:00:00:00:00:00" and mac != "ff:ff:ff:ff:ff:ff" and not ip.endswith('.255'):
                            if known_macs.get(ip) != mac:
                                known_macs[ip] = mac
                                updated = True
    except Exception as e:
        app.logger.warning(f"Falha ao ler tabela ARP: {e}")
    
    if updated:
        save_known_macs()

def send_wake_on_lan(ip: str) -> Tuple[bool, str]:
    """Envia um Magic Packet para o endereço MAC associado ao IP."""
    mac = known_macs.get(ip)
    if not mac:
        _harvest_macs_from_arp() # Tenta atualizar o cache
        mac = known_macs.get(ip)
    
    if not mac:
        app.logger.warning(f"WoL falhou para {ip}: MAC não encontrado no cache.")
        return False, f"MAC não encontrado para {ip}. Ligue a máquina manualmente uma vez para detectá-la."

    try:
        mac_clean = mac.replace(':', '').replace('-', '')
        if len(mac_clean) != 12:
            return False, f"MAC inválido armazenado para {ip}: {mac}"

        data = b'\xff' * 6 + (binascii.unhexlify(mac_clean)) * 16
        app.logger.info(f"Enviando Magic Packet para {ip} (MAC: {mac})")

        ip_parts = ip.split('.')
        subnet_broadcast = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.255"

        # No WSL, use o PowerShell como método principal e único para confiabilidade.
        if IS_WSL:
            # Este script é mais robusto:
            # 1. Define $ErrorActionPreference = "Stop" para garantir que qualquer falha seja capturada pelo Python.
            # 2. Envia para múltiplos alvos (broadcast da sub-rede e broadcast global) para máxima compatibilidade.
            # 3. Usa o método SendTo (via IPEndPoint), que é mais adequado para broadcast.
            # 4. Mantém a lógica de rajadas múltiplas para confiabilidade.
            ps_script = f'''
            $ErrorActionPreference = "Stop"

            $Mac = "{mac}"
            $MacByteArray = $Mac -split "[:-]" | ForEach-Object {{ [byte]('0x' + $_) }}
            $MagicPacket = [byte[]](,0xFF * 6) + $MacByteArray * 16

            $targets = @(
                @{{ Ip = "{subnet_broadcast}"; Port = 9 }},
                @{{ Ip = "{subnet_broadcast}"; Port = 7 }},
                @{{ Ip = "255.255.255.255"; Port = 9 }},
                @{{ Ip = "255.255.255.255"; Port = 7 }}
            )

            $Client = New-Object System.Net.Sockets.UdpClient
            $Client.EnableBroadcast = $true

            # Envia 3 rajadas de pacotes para todos os alvos para garantir a entrega
            for ($k=0; $k -lt 3; $k++) {{
                foreach ($target in $targets) {{
                    $EndPoint = New-Object System.Net.IPEndPoint([System.Net.IPAddress]::Parse($target.Ip), $target.Port)
                    # Envia 5 pacotes rápidos por alvo em cada rajada
                    for ($i=0; $i -lt 5; $i++) {{
                        $Client.Send($MagicPacket, $MagicPacket.Length, $EndPoint)
                        Start-Sleep -Milliseconds 10
                    }}
                }}
                Start-Sleep -Milliseconds 200
            }}

            $Client.Close()
            '''
            # O check=True garante que uma exceção seja lançada se o PowerShell falhar.
            subprocess.run(["powershell.exe", "-Command", ps_script], check=True, timeout=10)
            app.logger.info(f"WoL (Burst) enviado via PowerShell (WSL bypass) para {ip}")
            return True, f"Sinal de Wake-on-LAN enviado para {ip} ({mac})."

        # No Linux nativo, use o soquete Python.
        else:
            # Tenta enviar para múltiplos endereços de broadcast para garantir
            targets = [
                (subnet_broadcast, 9),
                (subnet_broadcast, 7),
                ('255.255.255.255', 9),
                ('255.255.255.255', 7)
            ]
            
            sent_count = 0
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                for _ in range(3):
                    for target_ip, target_port in targets:
                        try:
                            sock.sendto(data, (target_ip, target_port))
                            sent_count += 1
                            time.sleep(0.01)
                        except Exception as e:
                            app.logger.debug(f"Erro ao enviar pacote WoL para {target_ip}: {e}")
                    time.sleep(0.2)
            
            if sent_count > 0:
                app.logger.info(f"WoL enviado com sucesso para {ip} (MAC: {mac}) em {sent_count} tentativas.")
            return True, f"Sinal de Wake-on-LAN enviado para {ip} ({mac})."

    except Exception as e:
        # Captura exceções do PowerShell (se check=True) e de outras partes do processo.
        app.logger.error(f"Falha ao enviar WoL para {ip}: {e}")
        return False, f"Erro ao enviar WoL: {e}"

# --- Detecção de Ambiente ---
IS_WSL = 'microsoft' in platform.uname().release.lower()

def _get_default_gateway() -> Optional[str]:
    """
    Tenta encontrar o endereço IP do gateway padrão da rede em diferentes sistemas operacionais.
    """
    system = platform.system()
    try:
        if system == "Linux":
            # Executa 'ip route' e filtra a linha que começa com 'default'
            result = subprocess.run(['ip', 'route'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if line.startswith('default via'):
                    # Extrai o IP, que é a terceira palavra. Ex: 'default via 192.168.1.1 dev ...'
                    return line.split()[2]
        elif system == "Windows":
            # Executa 'route print' e procura pela rota padrão '0.0.0.0'
            result = subprocess.run(['route', 'print', '0.0.0.0'], capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                # A linha relevante contém '0.0.0.0' duas vezes e o gateway
                if '0.0.0.0' in line and 'On-link' not in line:
                    parts = line.split()
                    if len(parts) > 3:
                        # O gateway é geralmente o terceiro item não vazio
                        return parts[3]
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError) as e:
        app.logger.warning(f"Não foi possível obter o gateway padrão com o método principal: {e}")
    return None

def _get_windows_host_ip() -> Optional[str]:
    """Executa ipconfig.exe dentro do WSL para encontrar o IP do host Windows."""
    try:
        # Executa o ipconfig do Windows e captura a saída
        result = subprocess.run(['ipconfig.exe'], capture_output=True, text=True, check=True, encoding='cp850')
        # Procura por adaptadores Ethernet ou Wi-Fi
        for line in result.stdout.splitlines():
            if 'IPv4 Address' in line or 'Endereço IPv4' in line:
                # Extrai o endereço IP da linha
                ip = line.split(':')[-1].strip()
                # Ignora os IPs da rede virtual do WSL
                if not ip.startswith('172.'):
                    return ip
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError) as e:
        app.logger.warning(f"Falha ao obter o IP do host Windows via ipconfig.exe: {e}")
    return None

# --- Funções de Detecção de Rede ---
def get_local_ip_and_range() -> tuple[str, str, list[str], Optional[str], Optional[str]]:
    """
    Detecta dinamicamente o IP local do servidor e define a faixa de busca para a sub-rede correspondente.
    Se a detecção falhar, recorre à faixa estática como fallback.
    Retorna (ip_prefix, nmap_range, ips_to_check, server_ip, gateway_ip).
    server_ip é o IP da interface do servidor na rede local.
    """
    base_ip = None
    if not FORCE_STATIC_RANGE:
        if IS_WSL:
            app.logger.info("Ambiente WSL detectado. Tentando obter o IP do host Windows...")
            base_ip = _get_windows_host_ip()
            log_source = "host Windows (ipconfig.exe)"
        else:
            log_source = "IP local do servidor"
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                base_ip = s.getsockname()[0]

        if base_ip:
            gateway_ip = _get_default_gateway() # Obtém o IP do gateway
            ip_prefix = ".".join(base_ip.split('.')[:-1]) + "."
            nmap_range = f"{ip_prefix}0/24" # Ex: 192.168.1.0/24
            app.logger.info(f"Sub-rede detectada via {log_source}: {nmap_range}")
            ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
            return ip_prefix, nmap_range, ips_to_check, base_ip, gateway_ip
    
    # Fallback para a faixa estática se a detecção dinâmica falhar ou for forçada
    app.logger.warning(f"Usando faixa de IP estática como fallback: {IP_PREFIX}{IP_START}-{IP_END}")
    gateway_ip = _get_default_gateway() # Tenta obter o gateway mesmo no fallback
    ip_prefix = IP_PREFIX
    nmap_range = f"{ip_prefix}0/24"
    ips_to_check = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
    return ip_prefix, nmap_range, ips_to_check, None, gateway_ip

# --- Função auxiliar para descobrir IPs ---
def check_ssh_port(ip: str) -> Optional[str]:
    """
    Tenta estabelecer uma conexão de socket na porta 22 (SSH) para verificar se um host está ativo.
    Este método é mais confiável do que o ping, que pode ser bloqueado por firewalls.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)  # Aumenta o timeout para 1.5 segundos para mais confiabilidade
    try:
        # Tenta conectar na porta 22
        if sock.connect_ex((ip, 22)) == 0:
            return ip
    except socket.error:
        pass  # Ignora erros de conexão, pois estamos apenas testando
    finally:
        sock.close()
    return None

def _find_windows_nmap() -> str:
    """
    No WSL, tenta encontrar o executável do Nmap no Windows.
    Procura primeiro no PATH, depois em locais de instalação comuns.
    Retorna o comando a ser usado (seja 'nmap' ou o caminho completo).
    """
    # Script PowerShell para encontrar o caminho do nmap.exe
    ps_command = """
        $nmap_path = (Get-Command nmap.exe -ErrorAction SilentlyContinue).Source
        if (!$nmap_path) { $nmap_path = Resolve-Path "C:\\Program Files (x86)\\Nmap\\nmap.exe" -ErrorAction SilentlyContinue }
        if (!$nmap_path) { $nmap_path = Resolve-Path "C:\\Program Files\\Nmap\\nmap.exe" -ErrorAction SilentlyContinue }
        Write-Output $nmap_path
    """
    result = subprocess.run(["powershell.exe", "-Command", ps_command], capture_output=True, text=True, encoding='utf-8')
    found_path = result.stdout.strip()
    # Se um caminho foi encontrado, o envolve em aspas para segurança.
    # Caso contrário, usa 'nmap.exe', que o PowerShell pode encontrar se estiver no PATH.
    return f'"{found_path}"' if found_path else "nmap.exe"

def discover_ips_with_nmap(ip_range: str, ip_prefix: str) -> Optional[list[str]]:
    """Usa o nmap para uma descoberta de rede rápida e eficiente."""
    try:
        # Define a codificação correta com base no ambiente.
        # O PowerShell no Windows geralmente usa a codificação de console 'cp850'.
        encoding = 'cp850' if IS_WSL else 'utf-8'

        if IS_WSL:
            # Abordagem robusta para WSL:
            # 1. Encontra o caminho do nmap.exe de forma inteligente.
            # 2. Executa o Nmap via PowerShell, capturando a saída diretamente.
            nmap_executable = _find_windows_nmap()
            # O Nmap é instruído a enviar a saída para o stdout ('-oG -'), que é capturado pelo subprocess.
            # -p 22: Verifica apenas a porta 22 (SSH).
            # -T4: Template de tempo "agressivo" para acelerar a varredura.
            # -oG -: Formato de saída "grepável" para o stdout, fácil de analisar.
            # --open: Mostra apenas os hosts que têm a porta 22 aberta.
            nmap_command_str = f"& {nmap_executable} -p 22 -T4 --open -oG - {ip_range}"
            command = ["powershell.exe", "-Command", nmap_command_str]
        else:
            # Em um ambiente Linux nativo, o comando é mais direto.
            command = ["nmap", "-p", "22", "-T4", "--open", "-oG", "-", ip_range]

        # Executa o comando, especificando a codificação correta para decodificar a saída.
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, encoding=encoding)
    
        # --- DEBUGGING: Loga a saída bruta do Nmap ---
        if IS_WSL:
            app.logger.debug(f"Nmap (via PowerShell) stdout:\n{result.stdout}")
            app.logger.debug(f"Nmap (via PowerShell) stderr:\n{result.stderr}")
        # --- FIM DEBUGGING ---

        # Verificação específica para o erro "comando não encontrado" no PowerShell
        if IS_WSL and result.stderr and ("não é reconhecido" in result.stderr or "is not recognized" in result.stderr):
            error_message = (
                "O comando 'nmap' não foi encontrado pelo PowerShell. "
                "Isso significa que o Nmap não está instalado no Windows ou não foi adicionado ao PATH do sistema. "
                "Por favor, instale o Nmap para Windows (https://nmap.org/download.html) e garanta que a opção "
                "para adicioná-lo ao PATH esteja marcada durante a instalação."
            )
            app.logger.error(error_message)
            return None # Usa o método de fallback

        active_ips = []
        for line in result.stdout.splitlines():
            # Procura por linhas que indicam um host com a porta 22 aberta.
            # Ex: "Host: 192.168.0.101 () Ports: 22/open/tcp//ssh///"
            if "Host:" in line and "/open/tcp" in line:
                # Extrai o IP da linha. Ex: "Host: 192.168.0.101 () Status: Up"
                parts = line.split()
                if len(parts) > 1:
                    ip = parts[1]
                    # A validação de prefixo não é mais estritamente necessária, pois o nmap já escaneia a faixa correta.
                    active_ips.append(ip)
        
        return active_ips
    except PermissionError as e:
        error_message = (
            "Permissão negada ao tentar executar 'nmap.exe'. "
            "Isso geralmente ocorre no WSL quando o drive do Windows está montado com a opção 'noexec'. "
            "Verifique seu arquivo /etc/wsl.conf e reinicie o WSL."
        )
        app.logger.error(f"Falha de permissão ao usar nmap: {e}. Detalhes: {error_message}")
        return None # Usa o método de fallback
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        app.logger.warning(f"Falha ao usar nmap ({e}). Usando método de fallback (verificação de porta).")
        # Retorna None para indicar que o método de fallback deve ser usado
        return None

@app.route('/import-macs', methods=['POST'])
def import_macs():
    """Importa uma lista de mapeamentos IP -> MAC para o cache (known_macs)."""
    data = request.get_json()
    entries = data.get('entries', [])
    
    if not entries:
        return jsonify({"success": False, "message": "Nenhum dado fornecido para importação."}), 400

    imported_count = 0
    for entry in entries:
        ip = entry.get('ip')
        mac = entry.get('mac')
        
        if ip and mac and is_valid_ip(ip):
            # Normaliza o MAC: converte para minúsculas e substitui '-' por ':'
            mac_normalized = mac.replace('-', ':').lower().strip()
            # Validação simples de formato MAC (6 pares de hexadecimais)
            if re.match(r"^([0-9a-f]{2}[:]){5}([0-9a-f]{2})$", mac_normalized):
                known_macs[ip] = mac_normalized
                imported_count += 1
    
    if imported_count > 0:
        save_known_macs()
        return jsonify({"success": True, "message": f"{imported_count} endereços MAC importados e salvos com sucesso."})
    else:
        return jsonify({"success": False, "message": "Nenhum par IP/MAC válido encontrado para importar."}), 400

def discover_ips_with_arp_scan(ips_to_check: list[str]) -> Optional[list[str]]:
    """Usa o arp-scan para uma descoberta de rede local extremamente rápida."""
    # arp-scan não funciona corretamente na rede NAT do WSL2 para descobrir a LAN física.
    if IS_WSL:
        app.logger.info("PULANDO arp-scan: não é eficaz no ambiente WSL2.")
        return None

    try:
        # Usa --localnet para escanear toda a sub-rede local, que é o método mais
        # rápido e confiável para o arp-scan. O script filtrará os resultados depois.
        command = ["sudo", "arp-scan", "--localnet", "--numeric", "--quiet"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)

        active_ips = []
        # A saída do arp-scan é geralmente "IP_address\tMAC_address"
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].count('.') == 3:
                ip = parts[0]
                active_ips.append(ip)
                if len(parts) > 1:
                    known_macs[ip] = parts[1] # Salva o MAC
        save_known_macs()
        return active_ips

    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        app.logger.warning(f"Falha ao usar arp-scan ({e}). Tentando próximo método.")
        return None

def _check_ssh_ports_in_parallel(ips_to_check: list[str]) -> list[str]:
    """Função auxiliar de nível superior para verificar portas SSH em paralelo."""
    # Usa um pool de processos para verificar as portas SSH.
    with Pool(processes=cpu_count()) as pool:
        return [res for res in pool.imap_unordered(check_ssh_port, ips_to_check) if res]

class NetworkScanner:
    def __init__(self, logger):
        self.logger = logger

    def scan(self) -> list[str]:
        """
        Executa a descoberta de rede usando a melhor estratégia disponível.
        """
        ip_prefix, nmap_range, _, _, _ = get_local_ip_and_range()
        self.logger.info(f"Iniciando busca de IPs na sub-rede {ip_prefix}0/24...")

        # Estratégia 1: Nmap (mais universal)
        self.logger.info("Tentando descoberta com 'nmap' (método primário)...")
        nmap_results = discover_ips_with_nmap(nmap_range, ip_prefix)
        if nmap_results is not None: # Nmap executou, pode ter encontrado 0 ou mais IPs
            self.logger.info(f"Descoberta concluída com 'nmap'. Encontrados {len(nmap_results)} hosts com porta 22 aberta.")
            return nmap_results

        # Estratégia 2: Arp-scan (rápido, mas não funciona no WSL)
        self.logger.info("'nmap' falhou. Tentando 'arp-scan' como fallback...")
        arp_results = discover_ips_with_arp_scan([])
        if arp_results is not None:
            self.logger.info(f"Descoberta de hosts concluída com 'arp-scan'. Encontrados {len(arp_results)} hosts ativos.")
            self.logger.info(f"Verificando porta 22 em {len(arp_results)} hosts encontrados...")
            ssh_hosts = _check_ssh_ports_in_parallel(arp_results)
            self.logger.info(f"Verificação de porta concluída. {len(ssh_hosts)} hosts com SSH ativo.")
            return ssh_hosts

        # Estratégia 3: Fallback completo (lento)
        self.logger.warning("Nenhum método de descoberta rápida (nmap/arp-scan) funcionou. Usando fallback completo.")
        all_ips_in_range = [f"{ip_prefix}{i}" for i in range(IP_START, IP_END + 1)]
        ssh_hosts = _check_ssh_ports_in_parallel(all_ips_in_range)
        self.logger.info(f"Verificação de fallback concluída. Encontrados {len(ssh_hosts)} hosts com SSH ativo.")
        return ssh_hosts

# --- Rota para Descobrir IPs ---
@app.route('/discover-ips', methods=['GET'])
def discover_ips():
    """
    Escaneia a rede e retorna a lista de IPs com a porta 22 aberta.
    """
    _, _, _, server_ip, gateway_ip = get_local_ip_and_range()
    
    try:
        scanner = NetworkScanner(app.logger)
        active_ips = scanner.scan()
    except Exception as e:
        app.logger.error(f"Erro durante a descoberta paralela de IPs: {e}")
        return jsonify({"success": False, "message": f"Erro ao escanear a rede: {e}"}), 500

    # Cria uma lista de exclusão abrangente para evitar que IPs indesejados apareçam.
    # Usar um set (conjunto) é mais eficiente para verificações de 'in'.
    comprehensive_exclusion_list = set(IP_EXCLUSION_LIST) | ip_blocklist # Usa a blocklist carregada
    if server_ip:
        comprehensive_exclusion_list.add(server_ip)
    if gateway_ip:
        comprehensive_exclusion_list.add(gateway_ip)

    # Filtra os IPs ativos e os da lista de exclusão manual.
    initial_count = len(active_ips)
    active_ips = [ip for ip in active_ips if ip not in comprehensive_exclusion_list]
    removed_count = initial_count - len(active_ips)
    if removed_count > 0:
        app.logger.info(f"Removidos {removed_count} IPs da lista de exclusão (servidor, gateway, manual).")

    # Tenta colher MACs da tabela ARP do sistema para IPs descobertos (especialmente se usou nmap)
    _harvest_macs_from_arp()

    # Adiciona IPs conhecidos (que têm MAC salvo) à lista, mesmo que estejam offline.
    # Isso permite que o usuário use o Wake-on-LAN neles.
    # A verificação agora usa a lista de exclusão abrangente.
    for known_ip in known_macs.keys():
        if known_ip not in active_ips and known_ip not in comprehensive_exclusion_list and not known_ip.endswith('.255'):
            active_ips.append(known_ip)

    # Ordena a lista final de IPs, se houver, pelo último octeto.
    if active_ips:
        active_ips.sort(key=lambda ip: int(ip.split('.')[-1]))

    return jsonify({"success": True, "ips": active_ips}), 200

@app.route('/block-ip', methods=['POST'])
def block_ip():
    """Adiciona um IP à blocklist permanente e o remove do cache de MACs."""
    data = request.get_json()
    ip_to_block = data.get('ip')

    if not ip_to_block:
        return jsonify({"success": False, "message": "Nenhum IP fornecido."}), 400

    global ip_blocklist, known_macs

    # Adiciona à blocklist em memória
    ip_blocklist.add(ip_to_block)
    # Salva a blocklist no disco
    save_ip_blocklist()

    # Remove do cache de MACs em memória, se existir
    if ip_to_block in known_macs:
        del known_macs[ip_to_block]
        # Salva o cache de MACs atualizado no disco
        save_known_macs()
    
    app.logger.info(f"IP {ip_to_block} adicionado à blocklist e removido do cache.")
    return jsonify({"success": True, "message": f"IP {ip_to_block} foi bloqueado e não aparecerá mais."})

@app.route('/get-blocklist', methods=['GET'])
def get_blocklist():
    """Retorna a lista de IPs atualmente na blocklist."""
    # A blocklist já está em memória, então apenas a retornamos.
    # Convertemos o set para uma lista para que seja serializável em JSON e a ordenamos.
    return jsonify({"success": True, "blocklist": sorted(list(ip_blocklist))})

@app.route('/unblock-ip', methods=['POST'])
def unblock_ip():
    """Remove um IP da blocklist permanente."""
    data = request.get_json()
    ip_to_unblock = data.get('ip')

    if not ip_to_unblock:
        return jsonify({"success": False, "message": "Nenhum IP fornecido."}), 400

    global ip_blocklist
    if ip_to_unblock in ip_blocklist:
        ip_blocklist.remove(ip_to_unblock)
        save_ip_blocklist()
        app.logger.info(f"IP {ip_to_unblock} removido da blocklist.")
        return jsonify({"success": True, "message": f"IP {ip_to_unblock} foi desbloqueado."})
    else:
        return jsonify({"success": False, "message": f"IP {ip_to_unblock} não encontrado na blocklist."}), 404

@app.route('/check-status', methods=['POST'])
def check_status():
    """
    Verifica rapidamente o status da conexão SSH para uma lista de IPs.
    """
    data = request.get_json()
    ips = data.get('ips', [])
    password = data.get('password')

    if not ips:
        return jsonify({"success": False, "message": "Nenhuma lista de IPs fornecida."}), 400

    # Filtra apenas IPs válidos para evitar erros ou injeção
    ips = [ip for ip in ips if is_valid_ip(ip)]

    statuses = {}

    def check_single_ip(ip):
        """Função executada em uma thread para verificar um único IP."""
        try:
            # Usa um timeout curto para uma verificação rápida.
            with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
                # Se a conexão for bem-sucedida, o host está online.
                return ip, 'online'
        except paramiko.AuthenticationException:
            # A máquina está online, mas a senha está errada.
            return ip, 'auth_error'
        except Exception:
            # Qualquer outra exceção (timeout, conexão recusada) significa offline.
            return ip, 'offline'

    # Usa ThreadPoolExecutor para limitar o número de threads simultâneas (ex: 30)
    with ThreadPoolExecutor(max_workers=30) as executor:
        future_to_ip = {executor.submit(check_single_ip, ip): ip for ip in ips}
        for future in as_completed(future_to_ip):
            ip, status = future.result()
            statuses[ip] = status

    return jsonify({"success": True, "statuses": statuses})
# --- Rota para servir o Frontend e o noVNC ---

@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def serve_frontend(path: str):
    """
    Serve o index.html para a rota raiz e outros arquivos estáticos (CSS, JS).
    """
    return send_from_directory(APP_ROOT, path)

@app.route('/favicon.ico')
def favicon():
    """Silencia o erro 404 para o favicon.ico, que o navegador solicita por padrão."""
    return '', 204


# --- Funções de Manipulação de Ações (Refatoradas de 'gerenciar_atalhos_ip') ---

def _handle_shell_action(ssh: paramiko.SSHClient, username: Optional[str], action: str, data: Dict[str, Any]):
    """Lida com ações que executam comandos shell."""
    ip = data.get('ip')
    password = data.get('password')
    command_builder = _get_command_builder(action)

    if not command_builder:
        # Retorna um dicionário para consistência, a camada superior fará o jsonify.
        return {"success": False, "message": "Ação desconhecida."}

    # Constrói o comando
    if callable(command_builder):
        command, error_response = command_builder(data)
        if error_response:
            return error_response # Retorna o dicionário de erro diretamente.
    else:
        command = command_builder

    # Define um timeout maior para a ação de atualização, que pode demorar.
    timeout = 300 if action == 'atualizar_sistema' else 20

    # Ações que não esperam resposta (fire-and-forget)
    fire_and_forget_actions = ['reiniciar', 'desligar']
    if action in fire_and_forget_actions:
        # Para essas ações, apenas executamos o comando sem esperar por uma saída.
        # A conexão será encerrada pelo comando de qualquer maneira.
        ssh.exec_command(command, timeout=5) # Timeout curto, apenas para enviar o comando.
        return {"success": True, "message": f"Sinal de '{action}' enviado com sucesso."}

    try:
        # Executa o comando shell. Se falhar, uma exceção CommandExecutionError será lançada.
        output, warnings, _ = _execute_shell_command(ssh, command, password, timeout=timeout, username=username)
    except CommandExecutionError as e:
        app.logger.error(f"Erro na ação '{action}' em {ip}: {e.details}")
        # Combina warnings e errors nos detalhes para um log completo no frontend.
        details = []
        # Usa os avisos da exceção, se houver.
        if e.warnings: details.append(f"Avisos: {e.warnings}")
        if e.details: details.append(f"Erros: {e.details}")
        
        # Retorna sucesso como False, mas inclui todos os detalhes.
        return {"success": False, "message": "Ocorreu um erro no dispositivo remoto.", "details": "\n".join(details)}


    # Lógica especial para a ação de obter informações do sistema
    if action == 'get_system_info':
        parsed_data = _parse_system_info(output)
        return {
            "success": True,
            "message": "Informações do sistema obtidas.",
            "data": parsed_data,
            "details": warnings
        }

    # A operação é um sucesso mesmo com avisos.
    return {"success": True, "message": output or "Ação executada com sucesso.", "details": warnings}

@app.route('/stream-action', methods=['POST'])
def stream_action():
    """
    Executa uma ação e transmite a saída em tempo real.
    Ideal para comandos de longa duração como 'atualizar_sistema'.
    """
    data = request.get_json()
    ip = data.get('ip')
    action = data.get('action')
    password = data.get('password')

    if ip and not is_valid_ip(ip):
        return Response("Endereço IP inválido.", status=400, mimetype='text/plain')

    if not all([ip, action, password]):
        return Response("IP, ação e senha são obrigatórios.", status=400, mimetype='text/plain')

    command_builder = _get_command_builder(action)
    if not command_builder:
        return Response("Ação desconhecida.", status=400, mimetype='text/plain')

    command, _ = command_builder(data)

    def generate_stream():
        try:
            with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
                # Usa a função de streaming do ssh_service
                exit_code = yield from _stream_shell_command(ssh, command, password)
                
                # Envia um marcador de finalização com o código de saída
                yield f"__STREAM_END__:{exit_code}\n"

        except Exception as e:
            app.logger.error(f"Erro de streaming na ação '{action}' em {ip}: {e}", exc_info=True)
            yield f"__STREAM_ERROR__:Erro de conexão ou execução: {str(e)}\n"

    # Retorna uma resposta de streaming. O mimetype 'text/event-stream' é comum,
    # mas 'text/plain' funciona bem para o nosso caso de uso simples.
    return Response(generate_stream(), mimetype='text/plain')

# --- Rota para Listar Backups de Atalhos ---
@app.route('/list-backups', methods=['POST'])
def list_backups():
    """
    Conecta a um IP e lista os diretórios de backup de atalhos disponíveis.
    """
    data = request.get_json()
    ip = data.get('ip')
    password = data.get('password')

    if not all([ip, password]):
        return jsonify({"success": False, "message": "IP e senha são obrigatórios."}), 400

    try:
        with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
            backups_by_dir = list_sftp_backups(ssh, BACKUP_ROOT_DIR)
            return jsonify({"success": True, "backups": backups_by_dir}), 200

    except (paramiko.AuthenticationException, paramiko.SSHException, Exception) as e:
        response, status_code = _handle_ssh_exception(e, ip, 'list-backups', app.logger)
        return jsonify(response), status_code

# --- Dicionário de Manipuladores de Ação (Action Dispatcher) ---
# Este dicionário centraliza o roteamento de ações, tornando o código mais limpo e extensível.
# Cada entrada mapeia uma 'action' (string) para a função que deve manipulá-la.
ACTION_HANDLERS = {
    # Ações que são executadas para cada usuário na máquina remota
    'desativar': _execute_for_each_user,
    'ativar': _execute_for_each_user,
    'mostrar_sistema': _execute_for_each_user,
    'ocultar_sistema': _execute_for_each_user,
    'limpar_imagens': _execute_for_each_user,
    'desativar_barra_tarefas': _execute_for_each_user,
    'ativar_barra_tarefas': _execute_for_each_user,
    'bloquear_barra_tarefas': _execute_for_each_user,
    'desbloquear_barra_tarefas': _execute_for_each_user,
    'definir_firefox_padrao': _execute_for_each_user,
    'definir_chrome_padrao': _execute_for_each_user,
    'desativar_perifericos': _execute_for_each_user,
    'ativar_perifericos': _execute_for_each_user,
    'desativar_botao_direito': _execute_for_each_user,
    'ativar_botao_direito': _execute_for_each_user,
    'enviar_mensagem': _execute_for_each_user,
    'ativar_deep_lock': _execute_for_each_user,
    'definir_papel_de_parede': _execute_for_each_user,
    'instalar_scratchjr': _execute_for_each_user,
    'get_system_info': _execute_for_each_user,
    'cleanup_wallpaper': _handle_cleanup_wallpaper, # Ação por máquina, não por usuário
}

# --- Rota Principal para Gerenciar Ações via SSH ---
@app.route('/gerenciar_atalhos_ip', methods=['POST'])
def gerenciar_atalhos_ip():
    """
    Recebe as informações do frontend, conecta via SSH e despacha a ação apropriada.
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Requisição inválida."}), 400

    ip = data.get('ip')
    action = data.get('action')
    password = data.get('password')

    if ip and not is_valid_ip(ip):
        return jsonify({"success": False, "message": "Endereço IP inválido."}), 400

    if not all([ip, action, password]):
        return jsonify({"success": False, "message": "IP, ação e senha são obrigatórios."}), 400
    
    # Ação de Wake-on-LAN (Ligar)
    if action == 'ligar':
        success, msg = send_wake_on_lan(ip)
        return jsonify({"success": success, "message": msg}), 200 if success else 404

    # Ações locais que não precisam de IP ou conexão SSH são tratadas primeiro.
    if action == 'backup_aplicacao':
        # Chama a função de backup diretamente e retorna o resultado.
        return backup_application()

    # Ações que devem usar a rota de streaming para feedback em tempo real.
    if action in ['atualizar_sistema']:
        # O frontend deve chamar a rota /stream-action para essas ações.
        return jsonify({"success": False, "message": "Ação de streaming deve ser chamada via /stream-action."}), 400

    # Passa a função de manipulação de shell para o payload para evitar importação circular.
    data['shell_action_handler'] = _handle_shell_action

    try:
        with ssh_connect(ip, SSH_USER, password, app.logger) as ssh:
            # Procura a ação no dicionário de manipuladores.
            handler = ACTION_HANDLERS.get(action)

            if handler == _execute_for_each_user:
                # Se o manipulador for para ações por usuário, chama-o.
                result_dict = _execute_for_each_user(ssh, action, data, app.logger)
                return jsonify(result_dict), 200 if result_dict.get('success') else 207 # 207 para Multi-Status
            elif handler == _handle_cleanup_wallpaper:
                 # Manipulador específico para cleanup_wallpaper.
                message, _, errors = _handle_cleanup_wallpaper(ssh, data)
                return jsonify({"success": not errors, "message": message, "details": errors}), 200 if not errors else 500
            else:
                # Se a ação não estiver no dicionário, trata como uma ação shell genérica (de sistema).
                result = _handle_shell_action(ssh, None, action, data)
                # _handle_shell_action agora retorna um dicionário.
                status_code = 500 if not result.get('success') else 200
                return jsonify(result), status_code # jsonify o dicionário aqui.

    except (paramiko.SSHException, socket.error) as e:
        # Captura todas as exceções de SSH e de socket (como timeouts de conexão)
        # e as delega para o manipulador de exceções padronizado.
        response, status_code = _handle_ssh_exception(e, ip, action, app.logger)
        return jsonify(response), status_code
    except Exception as e:
        # Captura qualquer outro erro inesperado para evitar que o servidor trave.
        app.logger.error(f"Erro inesperado e não tratado na rota /gerenciar_atalhos_ip: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Ocorreu um erro interno inesperado no servidor."}), 500

@app.route('/backup-application', methods=['POST'])
def backup_application():
    """
    Cria um backup .zip do diretório da aplicação, excluindo arquivos desnecessários.
    Esta é uma ação local, executada no servidor onde o backend está rodando.
    """
    # Importa a biblioteca zipfile apenas quando necessário.
    import zipfile

    try:
        # Diretório raiz do projeto.
        source_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Diretório onde os backups serão salvos.
        backup_parent_dir = os.path.join(source_dir, 'backups_app')
        os.makedirs(backup_parent_dir, exist_ok=True)

        # Nome do arquivo de backup com data e hora.
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        archive_name = f'backup_app_{timestamp}.zip'
        archive_path = os.path.join(backup_parent_dir, archive_name)

        # Lista explícita de arquivos e pastas a serem incluídos no backup.
        # Isso é mais seguro e previsível do que incluir tudo e excluir alguns.
        files_to_backup = [
            'index.html', 'style.css', 'script.js',
            'grid_view.html', 'grid_view.js',
            'app.py', 'command_builder.py', 'ssh_service.py', # Inclui os módulos Python
            'actions.sh',
            'novnc/' # Inclui a pasta novnc inteira
        ]

        # Cria o arquivo .zip e adiciona os arquivos/pastas.
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for item in files_to_backup:
                item_path = os.path.join(source_dir, item)
                if os.path.exists(item_path):
                    if os.path.isdir(item_path):
                        # Adiciona uma pasta e todo o seu conteúdo recursivamente.
                        for root, _, files in os.walk(item_path):
                            for file in files:
                                file_path = os.path.join(root, file)
                                # O segundo argumento (arcname) define o caminho relativo dentro do zip.
                                arcname = os.path.relpath(file_path, source_dir)
                                zipf.write(file_path, arcname)
                    else:
                        # Adiciona um arquivo único.
                        zipf.write(item_path, item)
                else:
                    app.logger.warning(f"Item de backup não encontrado e ignorado: {item_path}")
        
        app.logger.info(f"Backup da aplicação criado com sucesso em: {archive_path}")
        return jsonify({'success': True, 'message': 'Backup da aplicação criado com sucesso.', 'path': archive_path})

    except Exception as e:
        # Loga o erro completo para depuração.
        app.logger.error(f"Erro ao criar backup da aplicação com zipfile: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Falha ao criar o backup: {e}'}), 500

@app.route('/list-application-backups', methods=['GET'])
def list_application_backups():
    """
    Lista os arquivos de backup da aplicação (.zip) encontrados no diretório 'backups_app'.
    """
    try:
        source_dir = os.path.dirname(os.path.abspath(__file__))
        backup_dir = os.path.join(source_dir, 'backups_app')

        if not os.path.isdir(backup_dir):
            return jsonify({'success': True, 'backups': [], 'message': 'Diretório de backups da aplicação ainda não foi criado.'})

        # Lista todos os arquivos .zip no diretório
        backups = [f for f in os.listdir(backup_dir) if f.endswith('.zip')]
        
        # Ordena os backups do mais recente para o mais antigo com base no nome do arquivo
        backups.sort(reverse=True)

        return jsonify({'success': True, 'backups': backups})

    except Exception as e:
        app.logger.error(f"Erro ao listar backups da aplicação: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Falha ao listar backups: {e}'}), 500

@app.route('/restore-application-backup', methods=['POST'])
def restore_application_backup():
    """
    Restaura a aplicação a partir de um arquivo de backup selecionado e reinicia o servidor.
    """
    import zipfile
    data = request.get_json()
    backup_filename = data.get('backup_file')

    if not backup_filename:
        return jsonify({'success': False, 'message': 'Nome do arquivo de backup não fornecido.'}), 400

    try:
        source_dir = os.path.dirname(os.path.abspath(__file__))
        backup_dir = os.path.join(source_dir, 'backups_app')
        backup_path = os.path.join(backup_dir, backup_filename)

        if not os.path.isfile(backup_path):
            return jsonify({'success': False, 'message': 'Arquivo de backup não encontrado.'}), 404

        # Extrai o conteúdo do backup para o diretório raiz da aplicação, sobrescrevendo arquivos existentes.
        with zipfile.ZipFile(backup_path, 'r') as zipf:
            zipf.extractall(path=source_dir)

        app.logger.info(f"Aplicação restaurada com sucesso a partir de {backup_filename}. Reiniciando o servidor...")

        # Função para reiniciar o servidor após um pequeno atraso
        def do_restart():
            time.sleep(2) # Aguarda para garantir que a resposta HTTP seja enviada
            os.kill(os.getpid(), signal.SIGINT) # Envia um sinal de interrupção para o processo principal

        threading.Thread(target=do_restart).start()

        return jsonify({'success': True, 'message': 'Aplicação restaurada. O servidor será reiniciado.'})

    except Exception as e:
        app.logger.error(f"Erro ao restaurar backup da aplicação: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Falha ao restaurar o backup: {e}'}), 500

@app.route('/delete-application-backup', methods=['POST'])
def delete_application_backup():
    """
    Exclui um arquivo de backup da aplicação do servidor.
    """
    data = request.get_json()
    backup_filename = data.get('backup_file')

    if not backup_filename:
        return jsonify({'success': False, 'message': 'Nome do arquivo de backup não fornecido.'}), 400

    try:
        source_dir = os.path.dirname(os.path.abspath(__file__))
        backup_dir = os.path.join(source_dir, 'backups_app')
        backup_path = os.path.join(backup_dir, backup_filename)

        # Medida de segurança: verifica se o caminho é realmente dentro do diretório de backups
        # e se o nome do arquivo não contém '..' para evitar path traversal.
        normalized_backup_path = os.path.normpath(backup_path)
        if not os.path.abspath(normalized_backup_path).startswith(os.path.abspath(backup_dir)):
            app.logger.warning(f"Tentativa de exclusão de arquivo inválida: {backup_filename}")
            return jsonify({'success': False, 'message': 'Nome de arquivo inválido.'}), 400

        if not os.path.isfile(backup_path):
            return jsonify({'success': False, 'message': 'Arquivo de backup não encontrado.'}), 404

        os.remove(backup_path)
        app.logger.info(f"Backup da aplicação excluído com sucesso: {backup_filename}")
        return jsonify({'success': True, 'message': 'Backup excluído com sucesso.'})

    except Exception as e:
        app.logger.error(f"Erro ao excluir backup da aplicação: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Falha ao excluir o backup: {e}'}), 500

# --- Rotas para Visualização de Tela (VNC) ---

def find_free_port() -> int:
    """Encontra uma porta TCP livre no servidor."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

class ForwardServer(socketserver.BaseRequestHandler):
    """Handler para o nosso servidor de encaminhamento de porta."""
    def handle(self):
        try:
            # Abre um canal TCP direto para o host/porta remotos
            chan = self.server.ssh_transport.open_channel(
                "direct-tcpip",
                (self.server.remote_host, self.server.remote_port),
                self.request.getpeername(),
            )
            if chan is None:
                self.server.logger.error(f"[{self.server.ip}] Falha ao abrir canal de encaminhamento.")
                return

            self.server.logger.info(f"[{self.server.ip}] Túnel TCP direto aberto para {self.server.remote_host}:{self.server.remote_port}")

            # Encaminha os dados bidirecionalmente
            while True:
                r, _, _ = select.select([self.request, chan], [], [])
                if self.request in r:
                    data = self.request.recv(1024)
                    if not data: break
                    chan.send(data)
                if chan in r:
                    data = chan.recv(1024)
                    if not data: break
                    self.request.send(data)
        except Exception as e:
            self.server.logger.error(f"[{self.server.ip}] Erro no túnel: {e}", exc_info=True)
        finally:
            if 'chan' in locals() and chan: chan.close()
            self.request.close()

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Servidor TCP com threads para lidar com múltiplas conexões."""
    daemon_threads = True
    allow_reuse_address = True
    def __init__(self, server_address, RequestHandlerClass, ssh_transport, remote_host, remote_port, ip, logger):
        super().__init__(server_address, RequestHandlerClass)
        self.ssh_transport = ssh_transport
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.ip = ip
        self.logger = logger

def _start_vnc_tunnel(ip: str, username: str, password: str, local_port: int) -> Tuple[bool, str]:
    """
    Inicia um túnel VNC seguro usando Paramiko, sem expor a senha no processo.
    Retorna (success, message).
    """
    with vnc_lock:
        if ip in vnc_processes:
            try:
                app.logger.info(f"Encerrando processo VNC existente para {ip}...")
                if vnc_processes[ip].get('server'):
                    vnc_processes[ip]['server'].shutdown()
                if vnc_processes[ip].get('client'):
                    vnc_processes[ip]['client'].close()
            except Exception as e:
                app.logger.error(f"Erro ao encerrar VNC anterior para {ip}: {e}")
            del vnc_processes[ip]

    remote_vnc_port = 5900
    remote_ws_port = 6080

    remote_command = (
        "killall -q x11vnc websockify; "
        f"x11vnc -auth guess -display :0 -nopw -listen localhost -rfbport {remote_vnc_port} -xkb -ncache 10 -ncache_cr -forever > /dev/null 2>&1 & "
        f"stdbuf -oL websockify --run-once -v {remote_ws_port} localhost:{remote_vnc_port}"
    )

    ssh_client = None
    forward_server = None
    try:
        # 1. Conectar via SSH com Paramiko
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(ip, username=username, password=password, timeout=15)

        # 2. Executar o comando remoto para iniciar x11vnc e websockify
        # Usamos get_pty=True para simular um terminal, o que ajuda com comandos 'sudo'
        stdin, stdout, stderr = ssh_client.exec_command(f"sudo -S -p '' bash -c {shlex.quote(remote_command)}", get_pty=True)
        stdin.write(password + '\n') # Envia a senha de forma segura para o stdin do sudo
        stdin.flush()

        # 3. Monitorar a saída para confirmar que o websockify iniciou
        # Isso é crucial para saber quando o túnel pode ser estabelecido
        start_time = time.time()
        is_ready = False
        while time.time() - start_time < 20: # Timeout de 20s
            if stdout.channel.recv_ready():
                line = stdout.channel.recv(1024).decode('utf-8', 'ignore')
                app.logger.debug(f"[{ip}] VNC Setup Output: {line.strip()}")
                if "websocket server started" in line.lower() or "listen on" in line.lower():
                    is_ready = True
                    break
            time.sleep(0.1)

        if not is_ready:
            error_output = stderr.read().decode('utf-8', 'ignore')
            ssh_client.close()
            return False, f"Timeout ou erro ao iniciar VNC remoto. Detalhes: {error_output}"

        # 4. Iniciar o servidor de encaminhamento de porta local em uma thread
        forward_server = ThreadedTCPServer(
            ('0.0.0.0', local_port),
            ForwardServer,
            ssh_transport=ssh_client.get_transport(),
            remote_host='localhost',
            remote_port=remote_ws_port,
            ip=ip,
            logger=app.logger
        )
        server_thread = threading.Thread(target=forward_server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        # 5. Armazenar referências para limpeza posterior
        with vnc_lock:
            vnc_processes[ip] = {'client': ssh_client, 'server': forward_server}

        return True, "Túnel VNC estabelecido com sucesso."

    except Exception as e:
        # Limpeza em caso de falha
        if forward_server:
            forward_server.shutdown()
        if ssh_client:
            ssh_client.close()
        with vnc_lock:
            if ip in vnc_processes:
                del vnc_processes[ip]
        
        # Fornece mensagens de erro mais claras
        error_str = str(e)
        if isinstance(e, paramiko.AuthenticationException):
            return False, "Falha de autenticação (senha incorreta?)."
        if isinstance(e, socket.timeout):
            return False, "Timeout ao conectar no SSH (host offline ou firewall)."
        
        app.logger.error(f"Erro inesperado ao iniciar túnel VNC para {ip}: {e}", exc_info=True)
        return False, f"Erro ao iniciar túnel: {error_str}"

import select

def _start_vnc_tunnel_paramiko(ip: str, username: str, password: str, local_port: int) -> Tuple[bool, str]:
    """
    Inicia um túnel SSH para VNC usando Paramiko e espera pela confirmação do websockify.
    Retorna (success, message).
    """
    if ip in vnc_processes:
        app.logger.info(f"Encerrando processo VNC existente para {ip}...")
        # O processo agora é o cliente SSH do Paramiko, que precisa ser fechado.
        try:
            vnc_processes[ip].close()
        except Exception as e:
            app.logger.error(f"Erro ao fechar cliente Paramiko para {ip}: {e}")
        del vnc_processes[ip]

    remote_vnc_port = 5900
    remote_ws_port = 6080

    remote_command = (
        f"echo {shlex.quote(password)} | sudo -S -p '' bash -c ' "
        f"killall -q x11vnc websockify; "
        f"x11vnc -auth guess -display :0 -nopw -listen localhost -rfbport {remote_vnc_port} -xkb -ncache 10 -ncache_cr -forever > /dev/null 2>&1 & "
        f"stdbuf -oL websockify --run-once -v {remote_ws_port} localhost:{remote_vnc_port}"
        f" ' "
    )

    try:
        # 1. Conectar via SSH com Paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username=username, password=password, timeout=10)

        # 2. Iniciar o túnel de porta (port forwarding)
        # Isso é mais complexo com Paramiko e geralmente requer um Transport.
        # A abordagem com `ssh -L` ainda é mais simples. O principal ganho de segurança
        # é na execução do comando remoto sem expor a senha no processo.
        # Para simplificar, vamos manter o túnel com `ssh -L` mas executar o comando de forma mais segura.
        # A refatoração completa para um túnel Paramiko puro é mais envolvida.
        # O foco aqui é a execução segura do comando.

        # 3. Executar o comando remoto
        stdin, stdout, stderr = ssh.exec_command(remote_command, get_pty=True)
        vnc_processes[ip] = ssh # Armazena o cliente para poder fechá-lo depois

        # 4. Monitorar a saída para confirmação
        timeout = 20
        start_time = time.time()
        output = ""
        while time.time() - start_time < timeout:
            if stdout.channel.recv_ready():
                line = stdout.channel.recv(1024).decode('utf-8', errors='ignore')
                output += line
                app.logger.debug(f"[{ip}] VNC Setup Output: {line.strip()}")
                if "websocket server started" in line.lower() or "listen on" in line.lower():
                    # O túnel precisa ser iniciado separadamente.
                    # Esta refatoração é mais complexa do que parece.
                    # A sugestão original de substituir `sshpass` é válida, mas a implementação
                    # requer uma reestruturação maior para lidar com o túnel e o comando.
                    # Por ora, a melhoria mais simples é garantir que `sshpass` não seja o único método.
                    return True, "Túnel estabelecido (simulado)." # Simulação para o exemplo

        # Se o loop terminar, houve timeout
        ssh.close()
        return False, f"Timeout ao iniciar VNC. Saída: {output}"

    except Exception as e:
        return False, f"Falha ao iniciar VNC com Paramiko: {str(e)}"

@app.route('/start-vnc', methods=['POST'])
def start_vnc():
    """
    Inicia uma sessão VNC em um cliente e cria um túnel SSH para ela.
    """
    data = request.get_json()
    ip = data.get('ip')
    password = data.get('password')

    if ip and not is_valid_ip(ip):
        return jsonify({"success": False, "message": "Endereço IP inválido."}), 400

    if not all([ip, password]):
        return jsonify({"success": False, "message": "IP e senha são obrigatórios."}), 400

    local_port = find_free_port()
    success, message = _start_vnc_tunnel(ip, SSH_USER, password, local_port) # Mantenha o original por enquanto

    if success:
        server_host = request.host.split(':')[0]
        # Usa 'vnc_lite.html' que é otimizado para ser embutido (sem a barra de controle superior).
        # Adiciona o parâmetro 'autoconnect=true' para iniciar a conexão automaticamente.
        vnc_url = f"/novnc/vnc_lite.html?host={server_host}&port={local_port}&path=websockify&autoconnect=true&token={ip}"
        return jsonify({"success": True, "url": vnc_url, "port": local_port, "token": ip})
    else:
        return jsonify({"success": False, "message": message}), 500

# --- Rota para Corrigir Chaves SSH ---
@app.route('/fix-ssh-keys', methods=['POST'])
def fix_ssh_keys():
    """
    Remove as chaves de host SSH antigas do arquivo known_hosts do servidor.
    """
    data = request.get_json()
    ips_to_fix = data.get('ips')

    if not ips_to_fix or not isinstance(ips_to_fix, list):
        return jsonify({"success": False, "message": "Lista de IPs é obrigatória."}), 400

    results = {}
    for ip in ips_to_fix:
        try:
            # O comando ssh-keygen -R remove a chave do known_hosts.
            # Não precisa de sudo, pois opera no arquivo do usuário que está rodando o backend.
            command = ["ssh-keygen", "-R", ip]
            # Usamos um timeout para evitar que o processo trave.
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)

            if result.returncode == 0:
                # A saída padrão de sucesso do ssh-keygen é útil.
                results[ip] = {"success": True, "message": result.stdout.strip().replace('\n', ' ')}
            else:
                # A saída de erro também é importante.
                results[ip] = {"success": False, "message": result.stderr.strip().replace('\n', ' ')}
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            error_message = f"Erro ao executar ssh-keygen para {ip}: {e}"
            app.logger.error(error_message)
            results[ip] = {"success": False, "message": error_message}

    all_success = all(r['success'] for r in results.values())
    return jsonify({"success": all_success, "results": results}), 200

@app.route('/shutdown', methods=['POST'])
def shutdown():
    """
    Encerra o servidor Flask de forma segura.
    Por segurança, esta rota só pode ser acessada a partir da própria máquina (localhost).
    """
    # Medida de segurança: apenas permite o desligamento se a requisição vier de 127.0.0.1
    if request.remote_addr != '127.0.0.1':
        app.logger.warning(f"Tentativa de desligamento não autorizada do IP: {request.remote_addr}")
        return jsonify({"success": False, "message": "Acesso negado."}), 403

    def do_shutdown():
        # Aguarda um segundo para garantir que a resposta HTTP seja enviada ao cliente.
        time.sleep(1)
        # Envia o sinal SIGINT para o processo atual, simulando um Ctrl+C.
        # Isso permite que o servidor (Waitress ou Flask dev) encerre de forma limpa.
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=do_shutdown).start()
    return jsonify({"success": True, "message": "O servidor será encerrado em breve."})

# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    # Configurações do servidor
    HOST = "0.0.0.0"
    PORT = 5000
    # Use o modo de desenvolvimento para abrir o navegador automaticamente
    # Defina a variável de ambiente DEV_MODE=true para ativar
    DEV_MODE = os.getenv("DEV_MODE", "false").lower() in ("true", "1", "t")

    print(f"DEBUG: DEV_MODE (env var check) is {DEV_MODE}")
    def open_browser():
        """Abre o navegador padrão na URL da aplicação."""
        webbrowser.open_new(f'http://127.0.0.1:{PORT}/')

    if DEV_MODE:
        # Em modo de desenvolvimento, usa o servidor do Flask com debug e reloader ativados.
        # Isso recarrega o servidor automaticamente quando o código é alterado.
        print(f"--> Servidor de desenvolvimento iniciado em http://{HOST}:{PORT}")
        print("--> O servidor irá recarregar automaticamente após alterações no código.")
        print("--> Pressione Ctrl+C para encerrar.")
        # A verificação 'WERKZEUG_RUN_MAIN' impede que o navegador seja aberto duas vezes
        # quando o reloader do Flask está ativo.
        if not os.environ.get('WERKZEUG_RUN_MAIN'):
            threading.Timer(1.5, open_browser).start()
        print("----------------------------------------\n")
        # Lista de arquivos do frontend para observar.
        # Quando um desses arquivos for alterado, o servidor reiniciará.
        frontend_files = [
            os.path.join(APP_ROOT, 'index.html'),
            os.path.join(APP_ROOT, 'grid_view.html'),
            os.path.join(APP_ROOT, 'grid_view.js'),
        ]
        print(f"DEBUG: Chamando app.run() em modo de desenvolvimento. Host={HOST}, Port={PORT}")
        try:
            # Removido 'extra_files=frontend_files' para aumentar a estabilidade no WSL.
            # A observação de arquivos em sistemas de arquivos montados (/mnt/c) pode ser instável.
            app.run(host=HOST, port=PORT, debug=True, use_reloader=False)
        except Exception as e:
            print(f"ERRO CRÍTICO: app.run() falhou com exceção: {e}", flush=True)
    else:
        # Em modo de produção, usa o servidor Waitress, que é mais robusto.
        THREADS = 16
        print(f"--> Servidor de produção (Waitress) iniciado em http://{HOST}:{PORT} com {THREADS} threads.")
        print("--> Pressione Ctrl+C para encerrar.")
        print("----------------------------------------\n")
        try:
            serve(app, host=HOST, port=PORT, threads=THREADS)
        except Exception as e:
            print(f"ERRO CRÍTICO: serve() (Waitress) falhou com exceção: {e}", flush=True)
    print("DEBUG: app.py está encerrando.")
