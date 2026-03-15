@echo off
echo ============================================
echo   SIGILO PAY - BUILD DO APLICATIVO CLIENTE
echo ============================================

cd /d "%~dp0"

echo [1/4] Instalando dependencias...
pip install requests pillow qrcode pyinstaller --quiet

echo [2/4] Gerando executavel...
pyinstaller --onefile --windowed --name "SigiloPay_Parceiro" ^
  --add-data "." ^
  app.py

echo [3/4] Pronto!
echo.
echo O arquivo EXE esta em: dist\SigiloPay_Parceiro.exe
echo.
pause
