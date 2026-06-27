FROM python:3.11-slim

WORKDIR /app

COPY src/ ./src/
COPY sample_data/ ./sample_data/

RUN pip install --no-cache-dir fastapi uvicorn pyyaml

EXPOSE 8000

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
