FROM python:3.11-slim

WORKDIR /app

# Install system deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc git && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ src/
COPY tests/ tests/
COPY config.yaml .env.example ./

# Install Python deps + pandas-ta (not on PyPI, install from vendored or ta fallback)
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir ta>=0.11

# Create data directory
RUN mkdir -p data

EXPOSE 8501

CMD ["streamlit", "run", "src/dashboard.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
