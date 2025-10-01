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

# Executa o app.py usando o interpretador Python do ambiente virtual para garantir
# que as dependências corretas sejam usadas.
"$VENV_DIR/bin/python" app.py "$@"