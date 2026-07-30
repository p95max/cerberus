FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN pip install --no-cache-dir "poetry>=2.0,<3.0"
COPY pyproject.toml ./
RUN poetry install --only main --no-root
COPY . ./

CMD ["sh", "-c", "uvicorn janus_service.app:app --host 0.0.0.0 --port ${JANUS_PORT:-8001}"]
