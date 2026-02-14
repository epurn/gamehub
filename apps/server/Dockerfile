FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV GAMEHUB_DATA_DIR=/data

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY apps /app/apps
COPY shared /app/shared

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "gamehub_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
