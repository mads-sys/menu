import socket
import time

s = socket.socket()
s.settimeout(4)
try:
    s.connect(('127.0.0.1', 6081))
    req = (
        b'GET /websockify HTTP/1.1\r\n'
        b'Host: 127.0.0.1:6081\r\n'
        b'Upgrade: websocket\r\n'
        b'Connection: Upgrade\r\n'
        b'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
        b'Sec-WebSocket-Version: 13\r\n'
        b'\r\n'
    )
    s.send(req)
    time.sleep(0.5)
    resp = s.recv(4096)
    print('RESP:', repr(resp[:200]))
except Exception as e:
    print('ERRO:', e)
finally:
    s.close()
