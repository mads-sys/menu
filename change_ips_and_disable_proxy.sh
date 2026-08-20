#!/bin/bash
# ==============================================================================
# Script de Alteração de IP (192.168.0.x -> 192.168.1.x) e Remoção de Proxy
# ==============================================================================
# Execução: sudo bash change_ips_and_disable_proxy.sh [SUBNET_ANTIGA] [SUBNET_NOVA] [GATEWAY_NOVO]
# Exemplo padrão: sudo bash change_ips_and_disable_proxy.sh 192.168.0. 192.168.1. 192.168.1.1

OLD_PREFIX="${1:-192.168.0.}"
NEW_PREFIX="${2:-192.168.1.}"
NEW_GATEWAY="${3:-192.168.1.1}"
NEW_DNS="${4:-1.1.1.1,8.8.8.8}"

echo "[+] Iniciando reconfiguração da máquina..."
echo "    De:  Subrede ${OLD_PREFIX}x"
echo "    Para: Subrede ${NEW_PREFIX}x"
echo "    Gateway Novo: ${NEW_GATEWAY}"

# ------------------------------------------------------------------------------
# 1. DESATIVAR PROXY (DCONF / GSETTINGS, ENV, APT)
# ------------------------------------------------------------------------------
echo "[+] 1/3 - Desativando Proxy no sistema..."

# A) Desativar em variáveis de ambiente (/etc/environment)
if [ -f /etc/environment ]; then
    echo "    -> Removendo variáveis de proxy de /etc/environment"
    sed -i '/http_proxy/d; /https_proxy/d; /ftp_proxy/d; /no_proxy/d' /etc/environment
    sed -i '/HTTP_PROXY/d; /HTTPS_PROXY/d; /FTP_PROXY/d; /NO_PROXY/d' /etc/environment
fi

# B) Desativar no APT (/etc/apt/apt.conf e /etc/apt/apt.conf.d/*)
if [ -f /etc/apt/apt.conf ]; then
    sed -i '/Acquire::http::Proxy/d; /Acquire::https::Proxy/d; /Acquire::ftp::Proxy/d' /etc/apt/apt.conf
fi
find /etc/apt/apt.conf.d/ -type f -exec sed -i '/Acquire::http::Proxy/d; /Acquire::https::Proxy/d; /Acquire::ftp::Proxy/d' {} + 2>/dev/null || true

# C) Desativar no GNOME (gsettings para usuários comuns)
USERS=$(ls /home 2>/dev/null; echo "aluno"; echo "root")
for u in $USERS; do
    USER_ID=$(id -u "$u" 2>/dev/null || true)
    if [ -n "$USER_ID" ]; then
        # Tenta aplicar via gsettings se houver ambiente gráfico ativo ou socket bus
        if [ -S "/run/user/$USER_ID/bus" ]; then
            sudo -u "$u" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" gsettings set org.gnome.system.proxy mode 'none' 2>/dev/null || true
            sudo -u "$u" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" gsettings set org.gnome.system.proxy.http host '' 2>/dev/null || true
            sudo -u "$u" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" gsettings set org.gnome.system.proxy.http port 0 2>/dev/null || true
        fi
    fi
done

# D) Desativar dconf padronizado globalmente (override)
mkdir -p /etc/dconf/db/local.d/
cat <<'EOF' > /etc/dconf/db/local.d/00-disable-proxy
[org/gnome/system/proxy]
mode='none'
EOF
dconf update 2>/dev/null || true

echo "    -> Proxy desativado com sucesso."

# ------------------------------------------------------------------------------
# 2. IDENTIFICAR E ALTERAR ENDEREÇO DE IP DA MÁQUINA
# ------------------------------------------------------------------------------
echo "[+] 2/3 - Reconfigurando endereço IP de ${OLD_PREFIX}x para ${NEW_PREFIX}x..."

CURRENT_IPS=$(hostname -I 2>/dev/null || ip addr show | grep 'inet ' | awk '{print $2}' | cut -d/ -f1)
CHANGED=false

for CURR_IP in $CURRENT_IPS; do
    if [[ "$CURR_IP" == ${OLD_PREFIX}* ]]; then
        HOST_PART="${CURR_IP#${OLD_PREFIX}}"
        NEW_IP="${NEW_PREFIX}${HOST_PART}"
        echo "    -> IP Atual detectado: ${CURR_IP}"
        echo "    -> Novo IP calculado: ${NEW_IP}"

        # A) Atualizar Netplan (/etc/netplan/*.yaml)
        if [ -d /etc/netplan ]; then
            for yaml_file in /etc/netplan/*.yaml; do
                if [ -f "$yaml_file" ]; then
                    echo "    -> Atualizando arquivo Netplan: $yaml_file"
                    cp "$yaml_file" "${yaml_file}.bak"
                    sed -i "s/${OLD_PREFIX}/${NEW_PREFIX}/g" "$yaml_file"
                    # Atualiza gateway antigo se necessário
                    sed -i "s/via: .*/via: ${NEW_GATEWAY}/g" "$yaml_file"
                    CHANGED=true
                fi
            done
        fi

        # B) Atualizar NetworkManager (nmcli)
        if command -v nmcli &>/dev/null; then
            CONN_NAME=$(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | grep ethernet | head -n 1 | cut -d: -f1)
            if [ -z "$CONN_NAME" ]; then
                CONN_NAME=$(nmcli -t -f NAME connection show 2>/dev/null | head -n 1)
            fi

            if [ -n "$CONN_NAME" ]; then
                echo "    -> Atualizando conexão NetworkManager: '$CONN_NAME'"
                nmcli con mod "$CONN_NAME" ipv4.addresses "${NEW_IP}/24" 2>/dev/null || true
                nmcli con mod "$CONN_NAME" ipv4.gateway "${NEW_GATEWAY}" 2>/dev/null || true
                nmcli con mod "$CONN_NAME" ipv4.dns "${NEW_DNS}" 2>/dev/null || true
                nmcli con mod "$CONN_NAME" ipv4.method manual 2>/dev/null || true
                CHANGED=true
            fi
        fi

        # C) Atualizar /etc/network/interfaces (Debian/Ubuntu legado)
        if [ -f /etc/network/interfaces ]; then
            echo "    -> Atualizando /etc/network/interfaces"
            sed -i "s/${OLD_PREFIX}/${NEW_PREFIX}/g" /etc/network/interfaces
            CHANGED=true
        fi
    fi
done

if [ "$CHANGED" = false ]; then
    echo "    [!] Nenhum IP correspondente a ${OLD_PREFIX}x foi encontrado nesta máquina."
    echo "    IPs atuais: ${CURRENT_IPS}"
fi

# ------------------------------------------------------------------------------
# 3. APLICAR MUDANÇAS DE REDE (DIFERIDO PARA NÃO DERRUBAR CONEXÃO SSH ABRUPTAMENTE)
# ------------------------------------------------------------------------------
echo "[+] 3/3 - Agendando aplicação da nova configuração de rede..."

(
    sleep 3
    if command -v netplan &>/dev/null; then
        netplan apply &>/dev/null || true
    fi
    if command -v nmcli &>/dev/null; then
        nmcli networking off &>/dev/null || true
        sleep 1
        nmcli networking on &>/dev/null || true
    fi
    systemctl restart networking &>/dev/null || true
    systemctl restart NetworkManager &>/dev/null || true
) &

echo "[✓] Processo concluído com sucesso! A rede será reiniciada em 3 segundos no novo IP."
