#!/bin/bash
# Testa o endpoint /api/start-vnc e a conexão websockify
IP="${1:-192.168.0.106}"

echo "=== Testando /api/start-vnc para IP=$IP ==="
curl -s -X POST http://127.0.0.1:5000/api/start-vnc \
  -H "Content-Type: application/json" \
  -d "{\"ip\": \"$IP\", \"username\": \"aluno\", \"password\": \"\"}" | python3 -m json.tool

echo ""
echo "=== Websockify na 6080 ==="
ss -tlnp | grep 6080

echo ""
echo "=== Teste WebSocket handshake ==="
source venv/bin/activate
python3 test_ws.py
