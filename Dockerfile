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

# Install Python deps
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir ta>=0.11

# Ensure src is on Python path
ENV PYTHONPATH=/app

# Create data directory
RUN mkdir -p data

EXPOSE 8000

CMD ["uvicorn", "src.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
