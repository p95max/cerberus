FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

RUN pip install --no-cache-dir "poetry>=2.0,<3.0"
RUN groupadd --system cerberus && useradd --system --gid cerberus --create-home cerberus
COPY pyproject.toml ./
RUN poetry install --only main --no-root
COPY . ./
RUN mkdir -p /app/staticfiles && chown -R cerberus:cerberus /app

USER cerberus

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2"]
