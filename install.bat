@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt
python -c "import config; print('Upstox configuration module OK; live orders remain disabled by default')"
