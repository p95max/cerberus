# Cerberus

Cerberus is a parking and vehicle access-control platform. It is maintained as
one product in a single monorepository.

## Architecture

- **Cerberus Core** (`backend/`) is the Django business platform, with
  PostgreSQL, Redis, Celery, and a documented REST API.
- **Janus** (`janus/`) is an internal FastAPI recognition service for ANPR/OCR
  and confidence scoring.
- **PostgreSQL** stores application data; **Redis** is reserved for cache and
  asynchronous-work needs.
- **Nginx** is the public edge. Routing to application services is added as
  those services expose their HTTP endpoints.

Access decisions remain deterministic business logic in Cerberus Core. Janus
provides recognition data only; it does not make access decisions.

## Repository layout

```text
backend/    Cerberus Core (Django)
janus/      Internal recognition service (FastAPI)
nginx/      Edge-proxy configuration
docker/     Shared container-related assets
docs/       Product and engineering documentation
scripts/    Developer and operational scripts
```

## Local setup

1. Install Docker Desktop, Python 3.12+, and Poetry.
2. Copy `.env.example` to `.env` if the default local ports or database values
   need changing. Never commit `.env`.
3. Install the service environments: `make install`.
4. Start the empty development stack: `docker compose up --build`.

Common commands are available through `make help`. On Windows, run the listed
Poetry and Docker commands directly if GNU Make is unavailable.

The backend exposes `/healthz`, `/readyz`, `/version`, `/api/schema/`, and
`/api/docs/`. Janus remains intentionally empty until its dedicated phase.
