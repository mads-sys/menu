#!/bin/bash
# Script para ativar o ambiente virtual, instalar dependências e iniciar o servidor.

# Muda para o diretório onde o script está localizado, para que possa ser executado de qualquer lugar.
cd "$(dirname "$0")"

set -e

VENV_DIR="venv"

# Cria o ambiente virtual se ele não existir
if [ ! -d "$VENV_DIR" ]; then
    echo "Criando o ambiente virtual..."
    python3 -m venv "$VENV_DIR"
fi

echo "Ativando o ambiente virtual..."
source "$VENV_DIR/bin/activate"

echo "Instalando/Atualizando dependências do arquivo requirements.txt..."
python -m pip install -r requirements.txt

echo ""
echo "========================================"
echo "Iniciando o servidor Flask com Waitress..."
echo "========================================"
python app.py