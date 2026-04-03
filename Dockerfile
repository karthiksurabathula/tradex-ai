FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install -e ".[dev]"
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "src/dashboard.py", "--server.address", "0.0.0.0"]
