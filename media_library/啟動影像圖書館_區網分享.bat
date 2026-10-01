@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
echo 區網其他電腦請以 http://本機IP:8765/ 連線
python server.py --host 0.0.0.0 --open %*
pause
