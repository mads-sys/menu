# Autonomous Execution
- Execute all safe code edits, file modifications, and terminal commands directly without requiring manual submit or interactive user confirmation.

# Projeto Menu - Arquitetura & Diretrizes

## Visão Geral do Sistema
- **Backend**: Python (Flask, Waitress WSGI, Flask-SocketIO, Paramiko SSH, Websockify, Pystray para bandeja do sistema).
- **Frontend**: HTML5, Vanilla JavaScript (`script.js`, `grid_view.js`, `constants.js`), CSS moderno (`style.css`, `grid_view.css`).
- **Comunicação Remota & VNC**: Conexões SSH seguras para automação em clientes remotos e streaming VNC via WebSocket / noVNC.
- **Banco de Dados**: SQLite (`app_data.db`, `menu.db`).
- **Sistema Operacional Principal**: Windows (PowerShell) controlando/interagindo com hosts Linux e ambientes locais.

## Padrões de Desenvolvimento
- **Segurança e Rede**: Garantir tratamento robusto de timeouts, desconexões e exceções de rede em chamadas SSH/VNC.
- **Concorrência**: Operações assíncronas e threads no backend devem ser seguras para acessos concorrentes ao SQLite e sockets.
- **Frontend Modular**: Manter código Vanilla JS limpo, aproveitando constantes centralizadas em `constants.js` e minimizando reflows desnecessários no DOM.
- **Scripts de Suporte**: Scripts `.sh` gerados para ambientes remotos devem manter compatibilidade com quebras de linha Unix (`LF`).
