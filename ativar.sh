#!/bin/bash

# Script para ativar o ambiente virtual, instalar dependências e iniciar o servidor.
# Garante que o script pare imediatamente se algum comando falhar.
set -e

# --- Determina o diretório do script para usar caminhos absolutos ---
# Isso torna o script robusto e executável de qualquer lugar, com ou sem sudo.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# --- Verificação de Dependências do Sistema ---
if ! command -v python3 &> /dev/null || ! command -v pip &> /dev/null; then
    echo "------------------------------------------------------------------"
    echo "ERRO: Python 3 e/ou pip não encontrados no sistema."
    echo "Por favor, instale-os para continuar."
    echo "Em sistemas baseados em Debian/Ubuntu, use o comando:"
    echo "sudo apt update && sudo apt install python3 python3-pip python3-venv"
    echo "------------------------------------------------------------------"
    exit 1
fi

# --- Configuração do Ambiente Virtual (usando caminho absoluto) ---
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Criando o ambiente virtual em '$VENV_DIR'..."
    python3 -m venv "$VENV_DIR"
fi

echo "Ativando o ambiente virtual..."
source "$VENV_DIR/bin/activate" # shellcheck disable=SC1091

# --- Instalação de Dependências do Python (usando caminho absoluto) ---
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
APP_FILE="$SCRIPT_DIR/app.py"

if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo "ERRO: Arquivo '$REQUIREMENTS_FILE' não encontrado."
    echo "Certifique-se de que o arquivo com as dependências do Python está na mesma pasta."
    exit 1
fi

echo "Instalando/atualizando dependências do arquivo '$REQUIREMENTS_FILE'..."
pip install -r "$REQUIREMENTS_FILE"

echo ""
echo "----------------------------------------"
echo "Iniciando o servidor..."

# Executa o servidor Python usando caminho absoluto
python3 "$APP_FILE"

