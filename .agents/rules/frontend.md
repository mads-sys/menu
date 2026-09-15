---
trigger:
  glob: "*.{js,html,css}"
---
# Diretrizes de Frontend (Web / UI)

- **Padrão Vanilla JS**: Manter arquitetura modular e legível sem frameworks pesados, aproveitando as configurações centralizadas em `constants.js`.
- **Renderização e Performance**: Evitar re-renderização completa do DOM em tabelas, listas e no grid de visualização (`grid_view.js`); atualizar nós cirurgicamente.
- **noVNC & Canvas RFB**: Garantir gerenciamento correto do ciclo de vida das conexões RFB/WebSocket ao alternar abas ou fechar previews noVNC.
- **Estilo & Temas**: Utilizar variáveis CSS para consistência visual (`style.css`, `grid_view.css`) e garantir suporte responsivo e contraste adequado para monitoramento.
