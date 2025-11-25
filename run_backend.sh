#!/usr/bin/env bash
# Script para configurar o ambiente virtual, instalar dependências e iniciar o servidor backend.

# --- Verificação de Bootstrap para Finais de Linha (CRLF) ---
# Este bloco é executado primeiro para detectar se o próprio script está com finais de linha do Windows.
# A variável '$0' contém o nome do interpretador que está executando o script.
# Se o script tiver finais de linha CRLF, o kernel tentará executar 'bash\r' em vez de 'bash'.
if [[ "$0" == *'\r' ]]; then
    # Define as cores aqui, pois o resto do script pode não ter sido carregado.
    RED='\033[0;31m'
    YELLOW='\033[1;33m'
    NC='\033[0m' # No Color
    echo -e "${RED}ERRO: O script está com finais de linha do Windows (CRLF).${NC}"
    echo -e "${YELLOW}Execute o seguinte comando para corrigi-lo e tente novamente:${NC}\n  sed -i 's/\\r\$//' \"$0\"\n"
    exit 1
fi

# --- Cores para o output ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Configuração de Segurança do Script ---
# set -e: Sair imediatamente se um comando falhar.
# set -u: Tratar variáveis não definidas como um erro.
# set -o pipefail: O status de saída de um pipeline é o do último comando a falhar.
set -euo pipefail

# --- Variáveis de Configuração ---
VENV_DIR="venv"                # Nome do diretório do ambiente virtual
REQUIREMENTS_FILE="requirements.txt" # Nome do arquivo de dependências
NOVNC_DIR="novnc"              # Nome do diretório do noVNC
FLASK_PORT=5000                # Porta para o servidor Flask


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

# 1. Verifica se o comando 'python3' está disponível.
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}ERRO: O comando 'python3' não foi encontrado. Por favor, instale o Python 3.${NC}"
    exit 1
fi

# 1. Verifica se o ambiente virtual é válido. Se o script de ativação não existir,
#    remove o diretório antigo (se houver) e cria um novo.
if [ ! -f "$VENV_ACTIVATE" ]; then
    echo -e "${YELLOW}Ambiente virtual inválido ou não encontrado. Recriando...${NC}"
    rm -rf "$VENV_DIR"
    echo -e "${YELLOW}Criando ambiente virtual em '$VENV_DIR'...${NC}"
    python3 -m venv "$VENV_DIR"
fi

# 2. Ativa o ambiente virtual.
echo -e "${GREEN}Ativando o ambiente virtual...${NC}"
source "$VENV_ACTIVATE"

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

if [ -f "$REQS_HASH_FILE" ] && [ "$(cat "$REQS_HASH_FILE")" == "$current_hash" ]; then
    echo -e "${GREEN}Dependências já estão atualizadas.${NC}"
else
    echo -e "${YELLOW}Instalando/atualizando dependências...${NC}"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS_FILE"
    echo "$current_hash" > "$REQS_HASH_FILE"
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

# A parte de configuração do sudoers para arp-scan é mantida separada,
# pois 'ensure_command' apenas instala o pacote, não configura permissões.
if command -v arp-scan &> /dev/null; then # Verifica se arp-scan está disponível (pode ter sido instalado agora)
    # Tenta executar um comando de busca real sem senha para garantir que as permissões estão corretas.
    # Usamos '127.0.0.1' como um alvo inofensivo apenas para testar a permissão.
    if ! sudo -n arp-scan --quiet --numeric 127.0.0.1 &> /dev/null; then
        echo -e "${YELLOW}AVISO: 'arp-scan' requer senha para ser executado, o que impedirá a busca de IPs.${NC}"
        echo -e "${GREEN}--> Adicionando permissão para 'arp-scan' no sudoers automaticamente...${NC}"
        echo "$USER ALL=(ALL) NOPASSWD: $(command -v arp-scan)" | sudo tee /etc/sudoers.d/99-arp-scan-no-password > /dev/null
        echo -e "${GREEN}--> Permissão concedida. Por favor, reinicie este script para que as alterações tenham efeito.${NC}"
        exit 0
    fi
fi
echo "" # Adiciona uma linha em branco para consistência

# --- Verificação e Instalação de Ferramentas de Rede (nmap) ---
ensure_command "nmap"

# --- Aviso para Usuários WSL ---
if grep -q -i "microsoft" /proc/version || [ -n "$WSL_DISTRO_NAME" ]; then
    echo -e "${YELLOW}--> Verificando se o Nmap está instalado no Windows (necessário para WSL)...${NC}"
    # Script PowerShell para encontrar o nmap.exe, procurando no PATH e em locais comuns.
    # Ele retorna um status de saída 0 se encontrar, e 1 se não encontrar.
    ps_check_command="
        \$nmap_path = Get-Command nmap.exe -ErrorAction SilentlyContinue
        if (!\$nmap_path) { \$nmap_path = Resolve-Path \"C:\\Program Files (x86)\\Nmap\\nmap.exe\" -ErrorAction SilentlyContinue }
        if (!\$nmap_path) { \$nmap_path = Resolve-Path \"C:\\Program Files\\Nmap\\nmap.exe\" -ErrorAction SilentlyContinue }
        if (\$nmap_path) { exit 0 } else { exit 1 }
    "
    
    if ! powershell.exe -Command "$ps_check_command" &> /dev/null; then
        echo -e "${RED}ERRO (WSL): O comando 'nmap.exe' não foi encontrado no PATH do Windows.${NC}"
        echo -e "${YELLOW}Para que a busca de IPs funcione corretamente, você DEVE ter o Nmap instalado no Windows.${NC}"
        echo -e "${YELLOW}Baixe e instale a partir de: https://nmap.org/download.html${NC}"
        echo -e "${YELLOW}Durante a instalação, certifique-se de que a opção para adicionar o Nmap ao PATH do sistema esteja marcada.${NC}"
        # Pausa o script para garantir que o usuário veja a mensagem.
        read -p "Pressione Enter para continuar mesmo assim (a busca de IPs será MUITO LENTA)..."
        echo ""
    else
        echo -e "${GREEN}--> Nmap encontrado no Windows. A busca de IPs deve funcionar corretamente.${NC}"
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
    rm -rf "$NOVNC_ZIP" noVNC-master
    echo -e "${GREEN}noVNC configurado com sucesso!${NC}"
fi


echo "----------------------------------------"
# 5. Inicia o servidor Flask.
echo -e "${GREEN}Iniciando o servidor backend (app.py)...${NC}"
# Ativa o modo de desenvolvimento para que o navegador abra automaticamente.
export DEV_MODE=true

# --- Configuração do Navegador ---
# Detecta se está rodando no WSL para usar o navegador do Windows.
# Se não, permite que o sistema use o navegador padrão do Linux (ex: Firefox, Chrome).
if grep -q -i "microsoft" /proc/version || [ -n "$WSL_DISTRO_NAME" ]; then
    echo -e "${YELLOW}--> Ambiente WSL detectado. Configurando navegador do Windows...${NC}"
    # A abordagem moderna e mais confiável é usar 'wslview' (do pacote wsl-utils).
    if command -v wslview &> /dev/null; then
        # Define o BROWSER para um comando que o módulo 'webbrowser' do Python entende.
        # '%s' é o placeholder para a URL.
        export BROWSER='wslview %s'
        echo -e "${GREEN}--> Usando 'wslview' para abrir o navegador (método recomendado).${NC}"
    else
        # Fallback para o método antigo. Usar 'cmd.exe /c start' é mais robusto do que
        # invocar 'explorer.exe' diretamente para abrir URLs a partir do WSL.
        # O '%s' é o placeholder que o módulo 'webbrowser' do Python substituirá pela URL.
        # Isso evita a lógica interna do Python que pode causar a abertura de múltiplas abas.
        export BROWSER='cmd.exe /c start %s'
        echo -e "${YELLOW}--> AVISO: 'wslview' não encontrado. Usando 'cmd.exe /c start' como fallback.${NC}"
        echo -e "${YELLOW}--> Para uma experiência ideal, execute: 'sudo apt-get update && sudo apt-get install wsl-utils'${NC}"
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
# --- Verificação de Porta em Uso ---
# Garante que o lsof esteja instalado, pois é necessário para verificar a porta.
ensure_command "lsof"

    PID=$(lsof -t -i :$FLASK_PORT 2>/dev/null || true)

    # Remove espaços em branco e novas linhas do início e do fim da variável PID.
    PID=$(echo "$PID" | tr -d '[:space:]')

    if [ -n "$PID" ] && [[ "$PID" =~ ^[0-9]+$ ]]; then
        # Obtém o nome do comando para exibir ao usuário.
        PROCESS_NAME=$(ps -p "$PID" -o comm=)
        echo -e "${YELLOW}AVISO: A porta $FLASK_PORT já está em uso pelo processo '$PROCESS_NAME' (PID: $PID).${NC}"
        
        read -p "Deseja finalizar este processo para iniciar um novo? (s/N) " -r response
        if [[ "$response" =~ ^[Ss]$ ]]; then
            echo -e "${GREEN}--> Finalizando o processo $PID...${NC}"
            # Usa 'kill -9' para forçar o encerramento.
            if kill -9 "$PID"; then
                echo -e "${GREEN}--> Processo finalizado com sucesso.${NC}"
                # Aguarda um breve momento para a porta ser liberada pelo sistema operacional.
                sleep 1
            else
                echo -e "${RED}ERRO: Falha ao finalizar o processo $PID. Tente manualmente com 'kill -9 $PID'.${NC}"
                exit 1
            fi
        else
            echo -e "${RED}Operação cancelada. O servidor não será iniciado.${NC}"
            exit 1
        fi
    fi
    
    # Executa o app.py usando o interpretador Python do ambiente virtual para garantir
    # que as dependências corretas sejam usadas.
    # A saída é exibida diretamente no terminal.
    # O 'set +e' desabilita a saída imediata em caso de erro para que possamos capturar o status.
    set +e
    "$VENV_DIR/bin/python" app.py "$@"
    PYTHON_EXIT_STATUS=$?
    set -e # Reabilita a saída em caso de erro.
    
    # Adiciona uma linha em branco após a execução do script Python para separar a saída da mensagem de cleanup.
    echo ""
    
    if [ "$PYTHON_EXIT_STATUS" -ne 0 ]; then
    echo -e "${RED}ERRO: O script 'app.py' falhou. Verifique as mensagens de erro acima.${NC}"
    exit 1 # Força a saída do script com erro se o Python falhou.
fi