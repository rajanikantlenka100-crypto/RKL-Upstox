@echo off
cd /d "%~dp0"
python -c "from instruments.resolver import resolve_indices; print(resolve_indices()); print('INSTRUMENTS PASS')"
