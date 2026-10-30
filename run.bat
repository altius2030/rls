@echo off
echo ============================================
echo  Rongta Scale Exporter - Moy Sklad
echo ============================================
echo.

cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Activating virtual environment...
call .venv\Scripts\activate

echo Installing dependencies...
pip install -r requirements.txt -q

echo.
echo ============================================
echo  Starting server on http://0.0.0.0:8000
echo ============================================
echo.

uvicorn main:app --host 0.0.0.0 --port 8000 --reload
