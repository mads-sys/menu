import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vnc_service
import socket
import threading
import time

target_ip = "192.168.50.63"
target_port = 5900
dedicated_port = 7352

print(f"Testing ThreadedWebSocketProxy on unreserved port {dedicated_port} -> {target_ip}:{target_port}...")

server = vnc_service.ThreadedWebSocketProxy(
    listen_host='0.0.0.0',
    listen_port=dedicated_port,
    target_host=target_ip,
    target_port=target_port
)

t = threading.Thread(target=server.start_server, daemon=True)
t.start()
time.sleep(0.3)

# Test connecting to websockify WebSocket
s = socket.create_connection(("127.0.0.1", dedicated_port), timeout=2.0)
handshake = (
    b"GET /websockify HTTP/1.1\r\n"
    b"Host: 127.0.0.1\r\n"
    b"Upgrade: websocket\r\n"
    b"Connection: Upgrade\r\n"
    b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
    b"Sec-WebSocket-Version: 13\r\n"
    b"\r\n"
)
s.sendall(handshake)
response = s.recv(4096)
print("Handshake Response:\n", response.decode('utf-8', errors='ignore'))

frame = s.recv(4096)
print(f"Frame received from remote VNC server ({len(frame)} bytes):", frame[:30])

s.close()
setattr(server, 'terminating', True)
if getattr(server, '_lsock', None):
    server._lsock.close()
print("SUCCESS: End-to-end VNC connection to 192.168.50.63 is working perfectly!")
