#!/bin/bash
#
# Script para ativar ou desativar o botão direito do mouse em todos os dispositivos de ponteiro.
# Recebe a ação ('enable' or 'disable') como primeiro argumento.
# Este script deve ser executado no contexto do usuário com sessão gráfica.

set -euo pipefail # Sair em caso de erro

ACTION="${1:-}"

if [[ "$ACTION" != "enable" ]] && [[ "$ACTION" != "disable" ]]; then
    echo "Erro: Ação inválida. Use 'enable' ou 'disable'." >&2
    exit 1
fi

# O comando 'xinput' precisa do ambiente gráfico.
# O script Python que chama este deve garantir que o ambiente X11 está configurado.
if ! command -v xinput &> /dev/null; then
    echo "Erro: O comando 'xinput' não foi encontrado na máquina remota." >&2
    exit 1
fi

# Encontra IDs de todos os dispositivos de ponteiro (mouses, touchpads, etc.).
POINTER_IDS=$(xinput list | awk -F'=' '/slave\s+pointer/ {print $2}' | awk '{print $1}')

if [ -z "$POINTER_IDS" ]; then
    echo "Nenhum dispositivo de ponteiro (mouse/touchpad) encontrado."
    exit 0
fi

SUCCESS_COUNT=0
for id in $POINTER_IDS; do
    if [[ "$ACTION" == "disable" ]]; then
        # Desativa o botão direito (botão 3) mapeando-o para 0.
        xinput set-button-map "$id" 1 2 0 && SUCCESS_COUNT=$((SUCCESS_COUNT+1))
    else # enable
        # Restaura o mapeamento padrão para os 3 primeiros botões.
        xinput set-button-map "$id" 1 2 3 && SUCCESS_COUNT=$((SUCCESS_COUNT+1))
    fi
done

MESSAGE_ACTION=$([[ "$ACTION" == "enable" ]] && echo "ativado" || echo "desativado")
echo "Ação concluída. O botão direito foi ${MESSAGE_ACTION} em ${SUCCESS_COUNT} dispositivo(s)."