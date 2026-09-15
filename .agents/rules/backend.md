---
trigger:
  glob: "*.py"
---
# Diretrizes de Backend (Python)

- **Tratamento de Exceções SSH/VNC**: Em serviços como `ssh_service.py` e `vnc_service.py`, tratar explicitamente falhas de conexão, `socket.error`, `AuthenticationException` e `SSHException`.
- **Concorrência & SQLite**: Utilize conexões SQLite apropriadas por thread ou implemente mecanismos de lock onde houver escrita simultânea em `app_data.db` ou `menu.db`.
- **Servidor Flask / Waitress**: Mantenha rotas organizadas e utilize streaming ou background tasks para processos longos de varredura de rede e execução em lote.
- **Bandeja & Serviços (Pystray / Threads)**: Garanta encerramento limpo (clean shutdown) de threads de background e listeners ao fechar a aplicação.
