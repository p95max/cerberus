FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN pip install --no-cache-dir "poetry>=2.0,<3.0"
COPY pyproject.toml ./
RUN poetry install --only main --no-root
COPY . ./

# Phase 1 has no FastAPI application yet. Phase 7 replaces this with Janus.
CMD ["python", "-c", "import time; time.sleep(2147483647)"]
