@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 檢查 Python 套件...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo 套件安裝失敗，請確認已安裝 Python 3.9 以上版本
  pause
  exit /b 1
)
python server.py --open %*
pause
