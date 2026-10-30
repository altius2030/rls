@echo off
chcp 65001 >nul
cd /d "%~dp0"
python rongta_export.py
pause
