@echo off
echo === tradex-ai Setup ===

python --version || (echo Python 3.11+ required && exit /b 1)

if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\activate.bat

pip install -e ".[dev]"

if not exist ".env" (
    copy .env.example .env
    echo Created .env from template
)

mkdir data 2>nul

echo.
echo === Ready! ===
echo Start with Docker:    docker compose up
echo Start dashboard:      streamlit run src/dashboard.py
echo Start autopilot:      python -m src.autopilot
