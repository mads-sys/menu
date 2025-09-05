#!/bin/bash
# Script para configurar o ambiente virtual, instalar dependências e iniciar o servidor backend.

# --- Cores para o output ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Processamento de Argumentos ---
# Verifica se o primeiro argumento é --debug para ativar o modo de depuração nos scripts shell.
if [[ "$1" == "--debug" ]]; then
    echo -e "${YELLOW}--> Modo de depuração de scripts ativado.${NC}"
    export DEBUG_MODE=true
    shift # Remove o argumento --debug para não ser passado para o app.py
fi

# Garante que o script seja executado a partir do seu próprio diretório.
cd "$(dirname "$0")"

# Interrompe a execução se qualquer comando falhar.
set -e

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

# 4. Instala/atualiza as dependências a partir do requirements.txt.
echo -e "${YELLOW}Instalando/atualizando dependências...${NC}"
# Usa o pip do ambiente virtual para garantir consistência.
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r requirements.txt

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
    # Informa ao Python para usar o navegador do Windows ao rodar no WSL.
    export BROWSER=explorer.exe
    echo -e "${YELLOW}--> Ambiente WSL detectado. Usando o navegador do Windows.${NC}"
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