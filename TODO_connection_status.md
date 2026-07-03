# TODO - Bolinhas de status vermelhas mesmo conectadas

## Informação coletada
- O backend `/check-status` retorna `statuses[ip] = {status: 'online'|'offline'|'auth_error', ...}`.
- No frontend (`script.js`), as bolinhas são o elemento `.status-dot` dentro de cada `.ip-item`.
- No CSS, a cor do ponto depende das classes do card `.ip-item.status-online` / `.status-offline`.
- O código do frontend atualiza classes do card em `updateIpItemsStatus()` mas a bolinha pode ficar inconsistente se o update não estiver aplicando as classes esperadas.

## Plano de correção
1. Inspecionar no `script.js` o `updateIpItemsStatus(statuses)` para garantir que:
   - `status` venha sempre válido (fallback seguro).
   - as classes `status-online`/`status-offline` sejam aplicadas sempre.
2. Tornar a atualização da bolinha independente das classes do card, sincronizando diretamente o `.status-dot` com o `status` recebido.
3. Adicionar logs temporários (opcional) apenas se necessário para confirmar se `check-status` está retornando valores como esperado.
4. Testar:
   - após 30s do primeiro load
   - após clicar em “Recarregar lista”

## Arquivos envolvidos
- `script.js`
- `style.css` (se necessário, para garantir que as classes do ponto funcionem)

