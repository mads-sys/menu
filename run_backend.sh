#!/usr/bin/env bash
# Script para configurar o ambiente virtual, instalar dependências e iniciar o servidor backend.

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

VENV_DIR="venv"

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

# 3. Verifica se o requirements.txt existe antes de continuar.
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}ERRO: O arquivo 'requirements.txt' não foi encontrado neste diretório.${NC}"
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

current_hash=$(sha256sum requirements.txt | awk '{print $1}')

if [ -f "$REQS_HASH_FILE" ] && [ "$(cat "$REQS_HASH_FILE")" == "$current_hash" ]; then
    echo -e "${GREEN}Dependências já estão atualizadas.${NC}"
else
    echo -e "${YELLOW}Instalando/atualizando dependências...${NC}"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install -r requirements.txt
    echo "$current_hash" > "$REQS_HASH_FILE"
fi
echo ""

# --- Verificação e Instalação de Ferramentas de Rede (arp-scan) ---
if ! command -v arp-scan &> /dev/null; then
    echo -e "${YELLOW}AVISO: O comando 'arp-scan' não foi encontrado. Ele é o método mais rápido para a busca de IPs.${NC}"
    if command -v apt-get &> /dev/null; then
        read -p "Deseja tentar instalar 'arp-scan' agora? (s/N) " -r response
        echo
        if [[ "$response" =~ ^[Ss]$ ]]; then
            if ! sudo -n true 2>/dev/null; then
                echo -e "${RED}ERRO: O comando 'sudo' requer uma senha para continuar.${NC}"
                echo -e "${YELLOW}Por favor, execute 'sudo apt-get update && sudo apt-get install -y arp-scan' e rode este script novamente.${NC}"
                exit 1
            fi
            echo -e "${GREEN}--> Instalando 'arp-scan'...${NC}"
            sudo apt-get update && sudo apt-get install -y arp-scan
        else
            echo -e "${YELLOW}Instalação pulada. O sistema usará métodos de busca mais lentos.${NC}"
        fi
    else
        echo -e "${RED}AVISO: 'apt-get' não disponível. Por favor, instale 'arp-scan' manualmente.${NC}"
    fi
    echo ""
else
    # Tenta executar um comando de busca real sem senha para garantir que as permissões estão corretas.
    # Usar '--version' não é suficiente, pois a política do sudo pode ser específica para o comando com argumentos.
    # Usamos '127.0.0.1' como um alvo inofensivo apenas para testar a permissão.
    if ! sudo -n arp-scan --quiet --numeric 127.0.0.1 &> /dev/null; then
        echo -e "${YELLOW}AVISO: 'arp-scan' requer senha para ser executado, o que impedirá a busca de IPs.${NC}"
        echo -e "${YELLOW}Para que a busca de IPs funcione, é necessário permitir que seu usuário execute 'arp-scan' sem senha.${NC}"
        read -p "Deseja adicionar a configuração necessária ao 'sudoers' agora? (s/N) " -r response
        if [[ "$response" =~ ^[Ss]$ ]]; then
            echo -e "${GREEN}--> Adicionando permissão para 'arp-scan' no sudoers...${NC}"
            # Adiciona uma regra para o usuário atual poder rodar arp-scan sem senha.
            # Usa 'tee' para escrever o arquivo como root.
            echo "$USER ALL=(ALL) NOPASSWD: $(command -v arp-scan)" | sudo tee /etc/sudoers.d/99-arp-scan-no-password > /dev/null
            echo -e "${GREEN}--> Permissão concedida. Por favor, reinicie este script para que as alterações tenham efeito.${NC}"
            exit 0
        else
            echo -e "${RED}ERRO: Permissão negada. A busca de IPs não funcionará sem acesso ao 'arp-scan'.${NC}"
            echo -e "${YELLOW}Para corrigir manualmente, execute o seguinte comando e reinicie o script:${NC}"
            echo "  echo \"$USER ALL=(ALL) NOPASSWD: $(command -v arp-scan)\" | sudo tee /etc/sudoers.d/99-arp-scan-no-password"
            exit 1
        fi
    fi
fi


# --- Verificação e Instalação de Ferramentas de Rede (nmap) ---
if ! command -v nmap &> /dev/null; then
    echo -e "${YELLOW}AVISO: O comando 'nmap' não foi encontrado. Ele é recomendado para uma busca de IPs mais rápida e confiável.${NC}"
    if command -v apt-get &> /dev/null; then
        read -p "Deseja tentar instalar 'nmap' agora? (s/N) " -r response
        echo
        if [[ "$response" =~ ^[Ss]$ ]]; then
            if ! sudo -n true 2>/dev/null; then
                echo -e "${RED}ERRO: O comando 'sudo' requer uma senha para continuar.${NC}"
                echo -e "${YELLOW}Por favor, execute 'sudo apt-get update && sudo apt-get install -y nmap' e depois rode este script novamente.${NC}"
                exit 1
            fi
            echo -e "${GREEN}--> Instalando 'nmap'...${NC}"
            sudo apt-get update && sudo apt-get install -y nmap
        else
            echo -e "${YELLOW}Instalação do nmap pulada. O sistema usará um método de busca mais lento.${NC}"
        fi
    else
        echo -e "${RED}AVISO: 'apt-get' não disponível. Por favor, instale 'nmap' manualmente usando o gerenciador de pacotes do seu sistema.${NC}"
    fi
    echo ""
fi

# --- Verificação e Instalação do noVNC ---
NOVNC_DIR="novnc"
if [ ! -f "$NOVNC_DIR/vnc.html" ]; then
    echo -e "${YELLOW}Diretório 'novnc' não encontrado ou incompleto. Baixando e configurando...${NC}"
    
    # Verifica se 'unzip' está instalado e, se não, tenta instalá-lo.
    if ! command -v unzip &> /dev/null; then
        echo -e "${YELLOW}O comando 'unzip' é necessário, mas não foi encontrado.${NC}"
        # Verifica se 'apt-get' está disponível para tentar a instalação automática.
        if command -v apt-get &> /dev/null; then
            # Usa 'read' sem '-n 1' para maior compatibilidade. O usuário precisará pressionar Enter.
            # Salva a resposta em uma variável explícita para maior robustez.
            read -p "Deseja tentar instalar 'unzip' agora? (s/N) " -r response
            echo
            if [[ "$response" =~ ^[Ss]$ ]]; then
                # Verifica se o sudo requer uma senha antes de prosseguir.
                # O 'sudo -n true' falhará se uma senha for necessária.
                if ! sudo -n true 2>/dev/null; then
                    echo -e "${RED}ERRO: O comando 'sudo' requer uma senha para continuar com a instalação.${NC}"
                    echo -e "${YELLOW}Por favor, execute o seguinte comando em seu terminal para instalar o 'unzip' manualmente:${NC}"
                    echo "    sudo apt-get update && sudo apt-get install -y unzip"
                    echo -e "${YELLOW}Depois, execute este script (${0}) novamente.${NC}"
                    exit 1
                fi
                echo -e "${GREEN}--> Instalando 'unzip'...${NC}"
                sudo apt-get update && sudo apt-get install -y unzip # Agora só executa se a senha não for necessária.
            else
                echo -e "${RED}Instalação cancelada. O script não pode continuar sem 'unzip'.${NC}"
                exit 1
            fi
        else
            echo -e "${RED}ERRO: 'unzip' não encontrado e 'apt-get' não está disponível para instalação automática.${NC}"
            exit 1
        fi
    fi

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
PORT=5000
# Verifica se o comando 'lsof' está disponível.
if ! command -v lsof &> /dev/null; then
    echo -e "${YELLOW}AVISO: O comando 'lsof' não foi encontrado. Não é possível verificar se a porta $PORT está em uso.${NC}"
    echo -e "${YELLOW}Se o servidor falhar ao iniciar, pode ser necessário instalar o 'lsof' com 'sudo apt-get install lsof'.${NC}"
else
    # Tenta encontrar o PID do processo usando a porta. A flag '-t' retorna apenas o PID.
    # Redireciona o stderr para /dev/null para suprimir a mensagem de erro se nenhum processo for encontrado.
    PID=$(lsof -t -i :$PORT 2>/dev/null || true)

    if [ -n "$PID" ]; then
        # Obtém o nome do comando para exibir ao usuário.
        PROCESS_NAME=$(ps -p "$PID" -o comm=)
        echo -e "${YELLOW}AVISO: A porta $PORT já está em uso pelo processo '$PROCESS_NAME' (PID: $PID).${NC}"
        
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
fi

# Executa o app.py usando o interpretador Python do ambiente virtual para garantir
# que as dependências corretas sejam usadas.
"$VENV_DIR/bin/python" app.py "$@"