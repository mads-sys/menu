import websockify
import websockify.websocketproxy as wsp
import threading
import time
import socket
import select

class ThreadedWebSocketProxy(wsp.WebSocketProxy):
    def __init__(self, target_host, target_port, listen_host="0.0.0.0", listen_port=6999, **kwargs):
        super().__init__(
            RequestHandlerClass=wsp.ProxyRequestHandler,
            target_host=target_host,
            target_port=target_port,
            listen_host=listen_host,
            listen_port=listen_port,
            verbose=True,
            **kwargs
        )
        self.terminating = False

    def start_server(self):
        try:
            lsock = self.socket(
                self.listen_host, self.listen_port, False,
                self.prefer_ipv6,
                tcp_keepalive=self.tcp_keepalive,
                tcp_keepcnt=self.tcp_keepcnt,
                tcp_keepidle=self.tcp_keepidle,
                tcp_keepintvl=self.tcp_keepintvl
            )
        except OSError as e:
            self.msg("Opening socket failed: %s", str(e))
            return

        self._lsock = lsock
        self.started()

        try:
            while not getattr(self, 'terminating', False):
                try:
                    self.poll()
                    ready = select.select([lsock], [], [], 0.5)[0]
                    if lsock not in ready:
                        continue

                    startsock, address = lsock.accept()

                    def _client_worker(sock, addr):
                        try:
                            # Note: do NOT close sock immediately in parent
                            self.top_new_client(sock, addr)
                        except Exception as ex:
                            print(f"Exception in client thread: {ex}")
                        finally:
                            try:
                                sock.close()
                            except Exception:
                                pass

                    t = threading.Thread(
                        target=_client_worker,
                        args=(startsock, address),
                        daemon=True,
                        name=f"WSClient-{self.listen_port}-{address[0]}"
                    )
                    t.start()
                except Exception as ex:
                    if getattr(self, 'terminating', False):
                        break
                    time.sleep(0.05)
        finally:
            try:
                lsock.close()
            except Exception:
                pass

print("Testing ThreadedWebSocketProxy...")
proxy = ThreadedWebSocketProxy(target_host="127.0.0.1", target_port=5900, listen_port=6999)
t = threading.Thread(target=proxy.start_server, daemon=True)
t.start()
time.sleep(0.3)

# Test connecting to proxy
with socket.create_connection(("127.0.0.1", 6999), timeout=1.0) as s:
    print("Socket connected to 6999 successfully!")
    s.sendall(b"GET /websockify HTTP/1.1\r\nHost: 127.0.0.1:6999\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
    resp = s.recv(1024)
    print("Response received from websockify:\n", resp.decode('utf-8', errors='ignore'))

proxy.terminating = True
print("Test completed successfully!")
