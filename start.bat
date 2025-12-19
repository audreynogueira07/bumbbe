@echo off
set HTTP_PROXY=
set HTTPS_PROXY=

REM --- Configuração do Ambiente ---
cd venv
call .\Scripts\activate
cd ..

REM --- Inicia o Listener em uma NOVA janela ---
echo Iniciando o WhatsApp Listener (Worker)...
start "Bumbbe Chat WhatsApp Listener" python manage.py run_whatsapp_listener

REM --- Inicia o Servidor Django na janela ATUAL ---
echo Iniciando o Servidor Django...
python manage.py runserver 8899

pause