#!/bin/bash
set -e
echo "=== tradex-ai Setup ==="

# Check Python
python3 --version || { echo "Python 3.11+ required"; exit 1; }

# Create venv
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

# Install deps
pip install -e ".[dev]"

# Check PostgreSQL
if ! command -v psql &> /dev/null; then
    echo "WARNING: PostgreSQL not found. Install it or use: docker compose up db"
    echo "Using DATABASE_URL=${DATABASE_URL:-postgresql://tradex:tradex@localhost:5432/tradex}"
fi

# Copy .env if not exists
[ ! -f .env ] && cp .env.example .env && echo "Created .env from template"

# Create data directory
mkdir -p data

echo ""
echo "=== Ready! ==="
echo "Start with Docker:    docker compose up"
echo "Start dashboard:      streamlit run src/dashboard.py"
echo "Start autopilot:      python -m src.autopilot"
