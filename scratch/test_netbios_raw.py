import sys
import os
sys.path.insert(0, os.path.abspath('.'))
import socket
import time

def inspect_netbios_raw(ip):
    packet = b'\x80\x94\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x20\x43\x4b\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x41\x00\x00\x21\x00\x01'
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    sock.sendto(packet, (ip, 137))
    start_t = time.time()
    results = []
    try:
        while time.time() - start_t < 0.5:
            data, addr = sock.recvfrom(1024)
            if len(data) > 57:
                num_names = data[56]
                names = []
                for i in range(num_names):
                    offset = 57 + i * 18
                    if offset + 15 <= len(data):
                        n = data[offset:offset+15].decode('ascii', errors='ignore').strip()
                        flags = data[offset+15:offset+18]
                        names.append(n)
                results.append((addr, names))
    except Exception as e:
        pass
    finally:
        sock.close()
    return results

for ip in ['192.168.0.104', '192.168.0.105', '192.168.0.106', '192.168.0.107', '192.168.0.116']:
    res = inspect_netbios_raw(ip)
    print(f"IP {ip} NetBIOS response from:", res)
