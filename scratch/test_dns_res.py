import sys
import os
sys.path.insert(0, os.path.abspath('.'))

import socket
import re
import time
from network_service import _resolve_mdns_name, _resolve_netbios_name, resolve_remote_hostname

ips = [f"192.168.0.{100+i}" for i in range(1, 10)]
print("Testing resolution for IPs:", ips)

for ip in ips:
    mdns = _resolve_mdns_name(ip, timeout=0.2)
    netbios = _resolve_netbios_name(ip, timeout=0.2)
    full = resolve_remote_hostname(ip, timeout=0.2)
    print(f"IP: {ip} -> mdns: {mdns}, netbios: {netbios}, full: {full}")
