@echo off
title Pawbook - servidor + ngrok
cd /d "%~dp0"
chcp 65001 >nul

echo ==========================================
echo   PAWBOOK - iniciando con enlace publico (ngrok)
echo ==========================================
echo.

REM Activar entorno virtual si existe
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat

python --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No se encontro Python. Instalalo desde https://www.python.org/downloads/
  pause
  exit /b 1
)

REM Instalar dependencias solo si falta alguna
python -c "import fastapi, uvicorn, sqlalchemy, jinja2, multipart, itsdangerous, PIL, openai, pyngrok" >nul 2>&1
if errorlevel 1 (
  echo Instalando dependencias, solo la primera vez...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las dependencias.
    pause
    exit /b 1
  )
)

echo Nota: la cuenta gratuita de ngrok permite una sola sesion a la vez.
echo Si la web UFI esta publicada con ngrok, cierrala antes.
echo.

REM Inicia el servidor, abre el tunel de ngrok y copia el enlace publico al portapapeles.
REM Para usar un dominio fijo, define NGROK_DOMAIN en el archivo .env
python main.py --ngrok --abrir

echo.
echo Servidor y tunel detenidos.
pause
