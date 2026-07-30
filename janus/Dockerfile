FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "poetry>=2.0,<3.0"
COPY pyproject.toml ./
RUN poetry install --only main --no-root
COPY janus_service ./janus_service
RUN python -c "import janus_service.app"

CMD ["sh", "-c", "uvicorn janus_service.app:app --host 0.0.0.0 --port ${JANUS_PORT:-8001}"]

FROM runtime AS development

RUN poetry install --with dev --no-root
COPY tests ./tests

FROM runtime AS production
