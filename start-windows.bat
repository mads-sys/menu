@echo off
REM Define o título da janela do console para algo descritivo.
title Servidor de Gerenciamento

REM Navega para o diretório onde o script está localizado.
REM Isso torna o script portatil, funcionando mesmo que voce mova a pasta do projeto.
cd /d "%~dp0"

echo Verificando o ambiente virtual do Python...
IF NOT EXIST "venv\Scripts\activate.bat" (
    echo.
    echo ERRO: Ambiente virtual 'venv' nao encontrado.
    echo Por favor, execute 'python -m venv venv' primeiro.
    echo.
    pause
    exit /b
)

REM Ativa o ambiente virtual do Python. Este passo e crucial.
echo Ativando o ambiente virtual...
call venv\Scripts\activate.bat

echo.
echo Instalando/Verificando dependencias do Python a partir de requirements.txt...
pip install -r requirements.txt

echo.
echo Iniciando o servidor (frontend e backend)...
npm start