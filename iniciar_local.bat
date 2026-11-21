@echo off
title Pawbook - servidor local
cd /d "%~dp0"
chcp 65001 >nul

echo ==========================================
echo   PAWBOOK - iniciando en modo LOCAL
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
python -c "import fastapi, uvicorn, sqlalchemy, jinja2, multipart, itsdangerous, PIL, openai" >nul 2>&1
if errorlevel 1 (
  echo Instalando dependencias, solo la primera vez...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] No se pudieron instalar las dependencias.
    pause
    exit /b 1
  )
)

REM Inicia el servidor y abre el navegador en http://localhost:8001
python main.py --abrir

echo.
echo Servidor detenido.
pause
