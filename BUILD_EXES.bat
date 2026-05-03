@echo off
chcp 65001 > nul
echo ============================================================
echo   SIGILO PAY - BUILD COMPLETO (2 EXEs)
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/5] Instalando dependencias...
pip install fastapi uvicorn httpx pydantic requests pillow qrcode pyinstaller -q
if %errorlevel% neq 0 (
    echo ERRO ao instalar dependencias!
    pause
    exit /b 1
)

echo [2/5] Limpando builds anteriores...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__

echo [3/5] Gerando Painel Admin (EXE do servidor)...
pyinstaller --onefile --windowed ^
  --name "SigiloPay_Painel" ^
  --hidden-import uvicorn ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols ^
  --hidden-import uvicorn.protocols.http ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.lifespan ^
  --hidden-import uvicorn.lifespan.on ^
  --hidden-import fastapi ^
  --hidden-import httpx ^
  --hidden-import sqlite3 ^
  --add-data "servidor;servidor" ^
  painel_admin.py
if %errorlevel% neq 0 (
    echo ERRO ao gerar painel_admin.exe!
    pause
    exit /b 1
)

echo [4/5] Gerando App Cliente (EXE para parceiros)...
pyinstaller --onefile --windowed ^
  --name "SigiloPay_Cliente" ^
  --hidden-import requests ^
  --hidden-import PIL ^
  --hidden-import qrcode ^
  app_cliente\app.py
if %errorlevel% neq 0 (
    echo ERRO ao gerar app_cliente.exe!
    pause
    exit /b 1
)

echo [5/5] Pronto!
echo.
echo ============================================================
echo   ARQUIVOS GERADOS:
echo.
echo   SERVIDOR/ADMIN:
echo   dist\SigiloPay_Painel.exe  (use VOCE como dono)
echo.
echo   PARCEIROS:
echo   dist\SigiloPay_Cliente.exe (distribua para parceiros)
echo ============================================================
echo.
pause
