#!/bin/bash
#
# Script para ativar ou desativar todos os dispositivos de entrada (mouse, teclado, touchpad).
# Recebe a ação ('enable' or 'disable') como primeiro argumento.
# Este script deve ser executado no contexto do usuário com sessão gráfica.

set -euo pipefail # Sair em caso de erro

ACTION="${1:-}"

if [[ "$ACTION" != "enable" ]] && [[ "$ACTION" != "disable" ]]; then
    echo "Erro: Ação inválida. Use 'enable' ou 'disable'." >&2
    exit 1
fi

# O comando 'xinput' precisa do ambiente gráfico.
# O script Python que chama este deve garantir que DISPLAY e XAUTHORITY estão definidos.
if ! command -v xinput &> /dev/null; then
    echo "Erro: O comando 'xinput' não foi encontrado na máquina remota." >&2
    exit 1
fi

# Encontra IDs de todos os dispositivos de entrada escravos (teclados, mouses, touchpads).
# A expressão regular busca por 'keyboard', 'mouse', ou 'touchpad' para ser mais específico.
DEVICE_IDS=$(xinput list | awk '
    /slave/ && (tolower($0) ~ /keyboard|mouse|touchpad/) {
        for (i=1; i<=NF; i++) {
            if ($i ~ /^id=[0-9]+$/) {
                split($i, a, "=");
                print a[2];
            }
        }
    }
')

if [ -z "$DEVICE_IDS" ]; then
    echo "Nenhum dispositivo de entrada (mouse, teclado, touchpad) encontrado."
    exit 0
fi

SUCCESS_COUNT=0
for id in $DEVICE_IDS; do
    xinput "$ACTION" "$id" && SUCCESS_COUNT=$((SUCCESS_COUNT+1))
done

MESSAGE_ACTION=$([[ "$ACTION" == "enable" ]] && echo "ativados" || echo "desativados")
echo "Ação concluída. ${SUCCESS_COUNT} dispositivo(s) foram ${MESSAGE_ACTION}."