import re
from typing import Any, Dict, Optional, Tuple


SPEED_RE_MBPS = re.compile(r"(?P<val>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>G|GB|M|MB|K|KB)?\s*(?:b)?\s*/?\s*(?:s)?", re.IGNORECASE)


def parse_link_speed_to_mbps(speed_raw: str) -> Optional[float]:
    """Converte valores comuns de speed para Mbps.

    Exemplos aceitos:
    - "1000Mb/s" -> 1000
    - "100 Mb/s" -> 100
    - "1.0Gb/s" -> 1000
    - "1000" -> 1000 (assumindo Mbps)
    """
    if not speed_raw:
        return None

    s = speed_raw.strip()
    if not s:
        return None

    # Normaliza alguns formatos conhecidos
    s = s.replace(' ', '')
    s = s.replace('–', '-')

    # Se já vier só número
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", s):
        return float(s)

    # ethtool: "Speed: 1000Mb/s"
    # /sys: geralmente: "1000" (em Mbps) — mas às vezes pode vir "1000Mb/s" em alguns sistemas
    # Tentativa 1: extrair padrão <val><unit>
    m = re.search(r"(?P<val>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>[KMG])", s, re.IGNORECASE)
    if not m:
        # Tentativa 2: procurar "Mb/s" ou "Gb/s"
        if 'Gb/s' in s or 'Gbit/s' in s or 'Gbps' in s:
            m2 = re.search(r"([0-9]+(?:\.[0-9]+)?)", s)
            if m2:
                return float(m2.group(1)) * 1000
        if 'Mb/s' in s or 'Mbit/s' in s or 'Mbps' in s:
            m2 = re.search(r"([0-9]+(?:\.[0-9]+)?)", s)
            if m2:
                return float(m2.group(1))
        if 'Kb/s' in s or 'Kbit/s' in s or 'Kbps' in s:
            m2 = re.search(r"([0-9]+(?:\.[0-9]+)?)", s)
            if m2:
                return float(m2.group(1)) / 1000
        return None

    val = float(m.group('val'))
    unit = m.group('unit').upper()

    if unit == 'G':
        return val * 1000
    if unit == 'M':
        return val
    if unit == 'K':
        return val / 1000

    return None


def parse_ethtool_speed_line(ethtool_output: str) -> Optional[float]:
    """Parse do ethtool (espera algo como "Speed: 1000Mb/s")."""
    if not ethtool_output:
        return None

    # Procura linha com Speed
    # Ex: "Speed: 1000Mb/s"
    m = re.search(r"Speed:\s*([0-9]+(?:\.[0-9]+)?\s*[KMG]?\s*(?:b)?\s*/?\s*s?)", ethtool_output, re.IGNORECASE)
    if m:
        return parse_link_speed_to_mbps(m.group(1))

    # fallback: tenta extrair de qualquer ocorrência "<val><unit>b/s"
    m2 = re.search(r"([0-9]+(?:\.[0-9]+)?)(\s*)([KMG])\w*\/s", ethtool_output, re.IGNORECASE)
    if m2:
        return parse_link_speed_to_mbps(f"{m2.group(1)}{m2.group(3)}")

    return None


def parse_sysfs_speed_value(value: str) -> Optional[float]:
    """/sys/class/net/<iface>/speed costuma ser em Mbps como número (ex: "1000")."""
    if not value:
        return None
    s = value.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return parse_link_speed_to_mbps(s)


def parse_remote_speed_output(output: str) -> Tuple[Optional[str], Optional[float]]:
    """Extrai o nome da interface e a velocidade a partir da saída do comando."""
    if not output:
        return None, None

    iface = None
    speed_mbps = None

    # Encontra a interface
    # Ex: "IFACE: eth0" ou "IFACE:enp3s0"
    iface_match = re.search(r"IFACE:\s*([a-zA-Z0-9._-]+)", output, re.IGNORECASE)
    if iface_match:
        iface = iface_match.group(1).strip()

    # Encontra a velocidade usando parse_ethtool_speed_line
    speed_mbps = parse_ethtool_speed_line(output)
    if speed_mbps is None:
        # Tenta também procurar por qualquer linha com "Speed:" ou padrão de número
        speed_match = re.search(r"Speed:\s*([^\n]+)", output, re.IGNORECASE)
        if speed_match:
            speed_mbps = parse_link_speed_to_mbps(speed_match.group(1))

    return iface, speed_mbps


def get_remote_nic_speed(ssh: Any, password: str, logger: Any) -> Tuple[Optional[str], Optional[float]]:
    """Obtém a interface de rede ativa e a velocidade da placa no host remoto via SSH.
    Tenta ethtool e fallback para /sys/class/net/*/speed.
    """
    from ssh_service import _execute_shell_command
    cmd = (
        "IFACE=$(ip route | grep default | awk '{print $5}' | head -n1); "
        "if [ -z \"$IFACE\" ]; then "
        "  IFACE=$(ip link show up | awk -F': ' '/state UP/ {print $2}' | grep -v '^lo' | head -n1); "
        "fi; "
        "if [ -z \"$IFACE\" ]; then "
        "  IFACE=$(ls /sys/class/net/ | grep -v '^lo' | head -n1); "
        "fi; "
        "if [ -n \"$IFACE\" ]; then "
        "  echo \"IFACE: $IFACE\"; "
        "  if command -v ethtool >/dev/null 2>&1; then "
        "    SPEED_OUT=$(ethtool \"$IFACE\" 2>/dev/null | grep -i \"Speed:\"); "
        "    if [ -n \"$SPEED_OUT\" ]; then "
        "      echo \"$SPEED_OUT\"; "
        "      exit 0; "
        "    fi; "
        "  fi; "
        "  if [ -f \"/sys/class/net/$IFACE/speed\" ]; then "
        "    echo \"Speed: $(cat /sys/class/net/$IFACE/speed)Mb/s\"; "
        "    exit 0; "
        "  fi; "
        "  for f in /sys/class/net/*; do "
        "    iface_name=$(basename \"$f\"); "
        "    if [ \"$iface_name\" != \"lo\" ] && [ -f \"$f/speed\" ]; then "
        "      echo \"IFACE: $iface_name\"; "
        "      echo \"Speed: $(cat \"$f/speed\")Mb/s\"; "
        "      exit 0; "
        "    fi; "
        "  done; "
        "  echo \"Speed: unknown\"; "
        "else "
        "  echo \"IFACE: unknown\"; "
        "  echo \"Speed: unknown\"; "
        "fi"
    )
    try:
        # Usa use_sudo=True para ter privilégios para ethtool e ler sysfs/speed se necessário
        output, _, _ = _execute_shell_command(ssh, cmd, password, timeout=15, use_sudo=True)
        logger.debug(f"NIC Speed output para {ssh.get_transport().getpeername()[0]}:\n{output}")
        return parse_remote_speed_output(output)
    except Exception as e:
        logger.error(f"Erro ao executar comando de velocidade de placa: {e}")
        return None, None


