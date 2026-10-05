#!/usr/bin/env bash
# Script para configurar o ambiente virtual, instalar dependências e iniciar o servidor backend.

# --- Verificação de Bootstrap para Finais de Linha (CRLF) ---
# Este bloco é executado primeiro para detectar se o próprio script está com finais de linha do Windows.
# No entanto, um script não pode corrigir a si mesmo se o sistema operacional não conseguir encontrar o interpretador 'bash\r'
# devido a finais de linha CRLF na linha shebang. Essa verificação inicial é, portanto, ineficaz para o próprio script
# e foi removida para maior clareza. A lógica subsequente que corrige *outros* scripts .sh é mantida, pois é útil.
# --- Cores para o output ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Colo

# --- Configuração de Segurança do Script ---
# set -e: Sair imediatamente se um comando falhar.
# set -u: Tratar variáveis não definidas como um erro.
# set -o pipefail: O status de saída de um pipeline é o do último comando a falhar.
set -euo pipefail

# --- Variáveis de Configuração ---
VENV_DIR="venv"                # Nome do diretório do ambiente virtual
REQUIREMENTS_FILE="requirements.txt" # Nome do arquivo de dependências
FLASK_PORT="${FLASK_PORT:-5950}"
export FLASK_PORT
NOVNC_DIR="novnc"              # Diretório para os arquivos do noVNC


# --- Verificação do Shell ---
# Garante que o script está sendo executado com Bash, não com PowerShell ou CMD.
if [ -z "${BASH_VERSION:-}" ]; then
    echo -e "${RED}ERRO: Este script deve ser executado com Bash.${NC}"
    echo -e "${YELLOW}Por favor, execute-o a partir de um terminal WSL (Ubuntu, Debian, etc.) ou Git Bash, não do PowerShell ou CMD.${NC}"
    exit 1
fi

# --- Verificação e Correção de Finais de Linha (CRLF para LF) ---
# Usa 'sed' para remover o caractere de retorno de carro (\r) dos scripts .sh.
# Isso evita a dependência do 'dos2unix' e aumenta a portabilidade.
echo -e "${GREEN}--> Verificando e corrigindo finais de linha dos scripts...${NC}"
for script_file in ./*.sh; do
    # A opção -i edita o arquivo no local.
    # A expressão 's/\r$//' substitui o caractere de retorno de carro no final da linha por nada.
    if [ -f "$script_file" ]; then
        sed -i 's/\r$//' "$script_file"
    fi
done

# --- Processamento de Argumentos ---
# Usa um loop para processar argumentos, permitindo mais flexibilidade no futuro.
while [[ $# -gt 0 ]]; do
    case "$1" in
        --debug)
            echo -e "${YELLOW}--> Modo de depuração de scripts ativado.${NC}"
            export DEBUG_MODE=true
            shift # Remove o argumento --debug
            ;;
        *)
            break # Para no primeiro argumento que não é uma flag conhecida
            ;;
    esac
done

# Garante que o script seja executado a partir do seu próprio diretório.
cd "$(dirname "$0")"

# Define o caminho para o script de ativação, que é padrão para ambientes Linux/WSL.
VENV_ACTIVATE="$VENV_DIR/bin/activate"
VENV_PYTHON="$VENV_DIR/bin/python"

# 1. Verifica se o comando 'python3' está disponível.
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERRO: O comando 'python3' não foi encontrado. Por favor, instale o Python 3.${NC}"
    exit 1
fi

# 1. Verifica se o ambiente virtual é válido e legível. Se não, recria.
if [ ! -f "$VENV_ACTIVATE" ] || [ ! -x "$VENV_PYTHON" ] || ! head -n 1 "$VENV_ACTIVATE" &> /dev/null; then
    echo -e "${YELLOW}Ambiente virtual inválido, corrompido ou inacessível. Recriando...${NC}"
    rm -rf "$VENV_DIR"
    echo -e "${YELLOW}Criando ambiente virtual em '$VENV_DIR'...${NC}"
    python3 -m venv "$VENV_DIR"
    if [ ! -x "$VENV_PYTHON" ]; then
        echo -e "${RED}ERRO: Falha ao criar o ambiente virtual. Verifique permissões ou bloqueios (OneDrive).${NC}"
        exit 1
    fi
fi

# 2. Ativa o ambiente virtual.
echo -e "${GREEN}Ativando o ambiente virtual...${NC}"
source "$VENV_ACTIVATE"

# 2.1 Garante que o pip esteja instalado no venv
if ! "$VENV_PYTHON" -m pip --version &> /dev/null; then
    echo -e "${YELLOW}--> Módulo 'pip' ausente no ambiente virtual. Inicializando pip...${NC}"
    "$VENV_PYTHON" -m ensurepip --upgrade &> /dev/null || true
    if ! "$VENV_PYTHON" -m pip --version &> /dev/null; then
        echo -e "${YELLOW}--> Baixando 'get-pip.py' para instalar o pip no ambiente virtual...${NC}"
        if command -v curl &> /dev/null; then
            curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && "$VENV_PYTHON" /tmp/get-pip.py --no-warn-script-location && rm -f /tmp/get-pip.py || true
        elif command -v wget &> /dev/null; then
            wget -qO /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py && "$VENV_PYTHON" /tmp/get-pip.py --no-warn-script-location && rm -f /tmp/get-pip.py || true
        fi
    fi
    if ! "$VENV_PYTHON" -m pip --version &> /dev/null; then
        if command -v apt-get &> /dev/null && command -v sudo &> /dev/null; then
            echo -e "${YELLOW}--> Tentando instalar python3-venv e python3-pip pelo gerenciador de pacotes...${NC}"
            sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv python3-pip python3-full || true
            rm -rf "$VENV_DIR"
            python3 -m venv "$VENV_DIR"
            source "$VENV_ACTIVATE"
        fi
    fi
fi

# Adiciona uma função de limpeza que será executada ao sair do script.
# O 'trap' captura os sinais de saída (EXIT), interrupção (INT, Ctrl+C) ou término (TERM).
function cleanup {
    # Verifica se o comando 'deactivate' (fornecido pelo ambiente virtual) existe.
    if command -v deactivate &> /dev/null; then
        echo -e "\n${YELLOW}--> Desativando o ambiente virtual...${NC}"
        deactivate
        echo -e "${GREEN}--> Ambiente virtual desativado. Encerrando.${NC}"
    else
        echo -e "\n${GREEN}--> Encerrando script.${NC}"
    fi
}
trap cleanup EXIT INT TERM

# --- Função para Detectar Gerenciador de Pacotes ---
function get_package_manager {
    if command -v apt-get &> /dev/null; then
        echo "apt-get"
    elif command -v dnf &> /dev/null; then
        echo "dnf"
    elif command -v yum &> /dev/null; then
        echo "yum"
    elif command -v pacman &> /dev/null; then
        echo "pacman"
    else
        echo "unknown"
    fi
}

# 3. Verifica se o requirements.txt existe antes de continuar.
if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo -e "${RED}ERRO: O arquivo '$REQUIREMENTS_FILE' não foi encontrado neste diretório.${NC}"
    echo -e "${RED}Por favor, crie o arquivo com as dependências do projeto.${NC}"
    exit 1
fi
# 4. Instala/atualiza as dependências de forma inteligente.
#    Apenas reinstala se o arquivo requirements.txt foi modificado.
REQS_HASH_FILE="$VENV_DIR/.reqs_hash"

# Verifica se o comando sha256sum está disponível.
if ! command -v sha256sum &> /dev/null; then
    echo -e "${RED}ERRO: O comando 'sha256sum' não foi encontrado. Não é possível verificar as dependências de forma otimizada.${NC}"
    echo -e "${RED}Por favor, instale o pacote 'coreutils'. Em sistemas Debian/Ubuntu: sudo apt-get install coreutils${NC}"
    exit 1
fi

current_hash=$(sha256sum "$REQUIREMENTS_FILE" | awk '{print $1}')

needs_install=false
if [ ! -f "$REQS_HASH_FILE" ] || [ "$(cat "$REQS_HASH_FILE" 2>/dev/null)" != "$current_hash" ]; then
    needs_install=true
elif ! "$VENV_PYTHON" -c "import flask, waitress, paramiko, flask_socketio" &> /dev/null; then
    echo -e "${YELLOW}--> Módulos principais (flask/waitress/paramiko) ausentes no ambiente virtual. Reinstalando...${NC}"
    needs_install=true
fi

if [ "$needs_install" = true ]; then
    echo -e "${YELLOW}Instalando/atualizando dependências...${NC}"
    "$VENV_PYTHON" -m pip install --upgrade pip || true
    "$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE"
    echo "$current_hash" > "$REQS_HASH_FILE"
else
    echo -e "${GREEN}Dependências já estão instaladas e verificadas.${NC}"
fi
echo ""

# --- Função para Verificar e Instalar Comandos ---
function ensure_command {
    local cmd=$1
    local pkg_name=${2:-$1} # Usa o nome do comando como nome do pacote, a menos que um segundo argumento seja fornecido.

    if command -v "$cmd" &> /dev/null; then
        # Se o comando já existe, não faz nada.
        return 0
    fi

    echo -e "${YELLOW}AVISO: O comando '$cmd' não foi encontrado.${NC}"
    if command -v apt-get &> /dev/null; then
        if ! sudo -n true 2>/dev/null; then
            echo -e "${RED}ERRO: O comando 'sudo' requer uma senha para continuar.${NC}"
            echo -e "${YELLOW}Por favor, execute 'sudo apt-get update && sudo apt-get install -y $pkg_name' e rode este script novamente.${NC}"
            exit 1
        fi
        echo -e "${GREEN}--> Instalando '$pkg_name' automaticamente...${NC}"
        sudo apt-get update && sudo apt-get install -y "$pkg_name"
    else
        echo -e "${YELLOW}AVISO: 'apt-get' não disponível. Por favor, instale '$pkg_name' manualmente.${NC}"
    fi
    echo ""
}

# --- Verificação e Instalação de Ferramentas de Rede (arp-scan) ---
ensure_command "arp-scan"

# Tenta atualizar a base de dados de fabricantes (OUI) para melhor identificação
if command -v get-arpscan-oui &> /dev/null; then
    echo -e "${GREEN}--> Atualizando base de dados de fabricantes do arp-scan...${NC}"
    sudo get-arpscan-oui > /dev/null 2>&1 || echo -e "${YELLOW}AVISO: Não foi possível atualizar a base OUI online.${NC}"
fi

# A parte de configuração do sudoers para arp-scan é mantida separada,
# pois 'ensure_command' apenas instala o pacote, não configura permissões.
if command -v arp-scan &> /dev/null; then # Verifica se arp-scan está disponível (pode ter sido instalado agora)
    # Testa se o comando arp-scan pode ser executado via sudo sem senha usando --version
    if ! sudo -n arp-scan --version &> /dev/null; then
        echo -e "${YELLOW}AVISO: 'arp-scan' requer senha para ser executado, o que impedirá a busca de IPs.${NC}"
        echo -e "${GREEN}--> Adicionando permissão para 'arp-scan' no sudoers automaticamente...${NC}"
        echo "$USER ALL=(ALL) NOPASSWD: $(command -v arp-scan)" | sudo tee /etc/sudoers.d/99-arp-scan-no-password > /dev/null
        echo -e "${GREEN}--> Permissão concedida.${NC}"
    fi
fi
echo "" # Adiciona uma linha em branco para consistência

# --- Verificação e Instalação de Ferramentas de Rede (nmap) ---
ensure_command "nmap"

# --- Aviso para Usuários WSL ---
if grep -q -i "microsoft" /proc/version || [ -n "${WSL_DISTRO_NAME:-}" ]; then
    echo -e "${YELLOW}--> Verificando se o Nmap está instalado no Windows (necessário para WSL)...${NC}"
    ps_check_command="
        \$nmap_path = Get-Command nmap.exe -ErrorAction SilentlyContinue
        if (!\$nmap_path) { \$nmap_path = Resolve-Path \"C:\\Program Files (x86)\\Nmap\\nmap.exe\" -ErrorAction SilentlyContinue }
        if (!\$nmap_path) { \$nmap_path = Resolve-Path \"C:\\Program Files\\Nmap\\nmap.exe\" -ErrorAction SilentlyContinue }
        if (\$nmap_path) { exit 0 } else { exit 1 }
    "
    
    POWERSHELL_BIN="powershell.exe"
    if [ -x "/init" ] && [ -x "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" ]; then
        POWERSHELL_BIN="/init /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    fi

    if $POWERSHELL_BIN -Command "$ps_check_command" &> /dev/null; then
        echo -e "${GREEN}--> Nmap encontrado no Windows. A busca de IPs deve funcionar corretamente.${NC}"
        echo ""
    else
        echo -e "${YELLOW}--> Nmap não foi detectado no Windows (usando varredura nativa paralela em Python).${NC}"
        echo ""
    fi
fi

# --- Verificação e Instalação do noVNC ---
# Garante que o diretório exista antes da verificação para evitar falhas em scripts subsequentes.
mkdir -p "$NOVNC_DIR"

if [ ! -f "$NOVNC_DIR/vnc.html" ]; then
    echo -e "${YELLOW}Diretório 'novnc' não encontrado ou incompleto. Baixando e configurando...${NC}"
    
    ensure_command "unzip"

    NOVNC_ZIP="novnc.zip"
    # URL para o zip da versão mais recente do noVNC
    NOVNC_URL="https://github.com/novnc/noVNC/archive/refs/heads/master.zip"
    
    echo -e "${GREEN}--> Baixando noVNC de $NOVNC_URL...${NC}"
    # Usa curl com -L para seguir redirecionamentos e -o para salvar no arquivo
    curl -L "$NOVNC_URL" -o "$NOVNC_ZIP"
    
    echo -e "${GREEN}--> Descompactando arquivos...${NC}"
    # Descompacta, sobrescrevendo arquivos existentes, e move o conteúdo para o diretório 'novnc'
    # Garante que o diretório de destino exista antes de mover os arquivos.
    mkdir -p "$NOVNC_DIR"
    unzip -o "$NOVNC_ZIP" -d .
    mv noVNC-master/* "$NOVNC_DIR/"
    
    echo -e "${GREEN}--> Limpando arquivos temporários...${NC}"
    rm -rf "$NOVNC_ZIP" noVNC-maste
    echo -e "${GREEN}noVNC configurado com sucesso!${NC}"
fi


echo "----------------------------------------"
# 5. Inicia o servidor Flask.
echo -e "${GREEN}Iniciando o servidor backend (app.py)...${NC}"
# Força o modo de desenvolvimento para que o navegador abra automaticamente.
# O auto-reloader será desativado no app.py para garantir estabilidade no WSL.
export DEV_MODE=true

# --- Configuração do Navegador ---
# Detecta se está rodando no WSL para usar o navegador do Windows.
# Se não, permite que o sistema use o navegador padrão do Linux (ex: Firefox, Chrome).
if grep -q -i "microsoft" /proc/version || [ -n "${WSL_DISTRO_NAME:-}" ]; then
    echo -e "${YELLOW}--> Ambiente WSL detectado. Configurando navegador do Windows...${NC}"
    # A abordagem moderna e mais confiável é usar 'wslview' (do pacote wsl-utils).
    if command -v wslview &> /dev/null; then
        export BROWSER='wslview %s'
        echo -e "${GREEN}--> Usando 'wslview' para abrir o navegador (método recomendado).${NC}"
    else
        if [ -x "/init" ] && [ -x "/mnt/c/Windows/System32/cmd.exe" ]; then
            export BROWSER='/init /mnt/c/Windows/System32/cmd.exe /c start %s'
        else
            export BROWSER='cmd.exe /c start %s'
        fi
        echo -e "${YELLOW}--> AVISO: 'wslview' não encontrado. Usando '/init cmd.exe /c start' como fallback.${NC}"
    fi
else
    # Em um ambiente Linux nativo, você pode descomentar uma das linhas abaixo
    # para forçar um navegador específico, ou deixar comentado para que o sistema
    # use o padrão (geralmente definido por xdg-settings).
    # export BROWSER=firefox
    # export BROWSER=google-chrome
    echo -e "${YELLOW}--> Ambiente Linux nativo detectado. Usando o navegador padrão do sistema.${NC}"
fi

echo ""
# --- Verificação e Liberação de Porta em Uso ---
echo -e "${YELLOW}--> Verificando se a porta $FLASK_PORT está em uso...${NC}"
# Tenta liberar com fuser, lsof e pkill se houver processo python antigo
if command -v fuser &> /dev/null; then
    fuser -k -9 "${FLASK_PORT}/tcp" &>/dev/null || true
fi

if command -v lsof &> /dev/null; then
    PIDS=$(lsof -t -i :"$FLASK_PORT" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        for P in $PIDS; do
            kill -9 "$P" 2>/dev/null || true
        done
    fi
fi

# Garante que processos residuais do app.py sejam encerrados
pkill -9 -f "venv/bin/python app.py" 2>/dev/null || true
sleep 1

    
    # --- Loop de Execução e Reinício Automático ---
    while true; do
        echo -e "${GREEN}--> Executando app.py...${NC}"
        export PYTHONUNBUFFERED=1 # Garante que o output do Python apareça imediatamente
        set +e
        "$VENV_PYTHON" app.py "$@"
        PYTHON_EXIT_STATUS=$?
        set -e # Reabilita a saída em caso de erro.
        
        echo ""
        if [ "$PYTHON_EXIT_STATUS" -eq 42 ]; then
            echo -e "${YELLOW}--> Reinício do servidor backend solicitado (Código 42).${NC}"
            echo -e "${YELLOW}--> Liberando porta ${FLASK_PORT} e reiniciando processo em 1 segundo...${NC}"
            if command -v fuser &> /dev/null; then
                fuser -k -9 "${FLASK_PORT}/tcp" &>/dev/null || true
            fi
            sleep 1
            continue
        elif [ "$PYTHON_EXIT_STATUS" -ne 0 ]; then
            echo -e "${RED}ERRO: O script 'app.py' encerrou com código de erro $PYTHON_EXIT_STATUS.${NC}"
            exit "$PYTHON_EXIT_STATUS"
        else
            echo -e "${GREEN}--> Backend finalizado normalmente.${NC}"
            break
        fi
    done