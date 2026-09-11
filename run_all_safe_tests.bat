@echo off
cd /d "%~dp0"
python -m unittest discover -s tests -p "test_*.py" -v
