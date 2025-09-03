#!/bin/bash
# Script para configurar o ambiente virtual, instalar dependências e iniciar o servidor backend.

# Garante que o script seja executado a partir do seu próprio diretório.
cd "$(dirname "$0")"

# Interrompe a execução se qualquer comando falhar.
set -e

VENV_DIR="venv"

# 1. Cria o ambiente virtual (venv) se ele ainda não existir.
if [ ! -d "$VENV_DIR" ]; then
    echo "Criando ambiente virtual em '$VENV_DIR'..."
    python3 -m venv "$VENV_DIR"
fi

# 2. Ativa o ambiente virtual.
echo "Ativando o ambiente virtual..."
source "$VENV_DIR/bin/activate"

# 3. Verifica se o requirements.txt existe antes de continuar.
if [ ! -f "requirements.txt" ]; then
    echo "ERRO: O arquivo 'requirements.txt' não foi encontrado neste diretório."
    echo "Por favor, crie o arquivo com as dependências do projeto."
    exit 1
fi

# 4. Instala/atualiza as dependências a partir do requirements.txt.
echo "Instalando dependências..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "----------------------------------------"
# 5. Inicia o servidor Flask.
echo "Iniciando o servidor backend (app.py)..."
# Ativa o modo de desenvolvimento para que o navegador abra automaticamente.
export DEV_MODE=true
# Informa ao Python para usar o navegador do Windows ao rodar no WSL.
export BROWSER=explorer.exe
python app.py "$@"