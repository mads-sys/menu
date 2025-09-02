@echo off
REM Define o título da janela do console para algo descritivo.
title Servidor de Gerenciamento

REM Navega para o diretório raiz do seu projeto.
cd "c:\Users\server\OneDrive\Documentos\GitHub_Menu\menu"

REM Exibe uma mensagem amigável e inicia o servidor.
echo Iniciando o servidor (frontend e backend)...
npm start

REM Mantém a janela aberta após a execução para que você possa ver os logs ou erros.
pause