# TODO - PopupBlocker (diagnóstico e robustez)

- [ ] Atualizar `command_builder.py`: tornar `verificar_bloqueio_popups` um relatório detalhado e tolerante a falhas (sem `set -e` + mensagens sobre caminhos e conteúdo encontrado).
- [ ] Atualizar `app.py`: garantir que `CommandExecutionError.details` seja retornado ao frontend corretamente (sem cair em mensagem genérica quando houver detalhes).
- [ ] (Se necessário) Ajustar parsing/limpeza em `ssh_service.py` para que `stderr` e exit_code não gerem exceção sem detalhes úteis.
- [ ] Testar fluxo: `bloquear_popups` -> `verificar_bloqueio_popups` -> `desbloquear_popups` em 1 IP que falha hoje.

