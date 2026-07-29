FROM python:3.12-slim

ARG INSTALL_DEV_DEPENDENCIES=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN pip install --no-cache-dir "poetry>=2.0,<3.0"
RUN groupadd --system cerberus && useradd --system --gid cerberus --create-home cerberus
COPY pyproject.toml ./
RUN if [ "$INSTALL_DEV_DEPENDENCIES" = "true" ]; then \
      poetry install --with dev --no-root; \
    else \
      poetry install --only main --no-root; \
    fi
COPY . ./
RUN mkdir -p /app/staticfiles && chown -R cerberus:cerberus /app

USER cerberus

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py ensure_test_operator && python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2"]
