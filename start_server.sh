#!/bin/bash
# Script para configurar o ambiente virtual, instalar dependências e iniciar o servidor de produção.

# Muda para o diretório onde o script está localizado, para que possa ser executado de qualquer lugar.
cd "$(dirname "$0")"

# Sai imediatamente se um comando falhar.
set -e

VENV_DIR="venv"

# Cria o ambiente virtual se ele não existir
if [ ! -d "$VENV_DIR" ]; then
    echo "-> Criando o ambiente virtual em '$VENV_DIR'..."
    python3 -m venv "$VENV_DIR"
fi

echo "-> Ativando o ambiente virtual..."
source "$VENV_DIR/bin/activate"

echo "-> Instalando/Atualizando dependências do requirements.txt..."
# Usar python3 para consistência e -m pip para robustez.
python3 -m pip install -r requirements.txt

echo ""
echo "========================================"
echo "Iniciando o servidor Flask com Waitress..."
echo "========================================"
python3 app.py