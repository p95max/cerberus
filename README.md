# Cerberus

Cerberus is a parking and vehicle access-control platform. It accepts vehicle-recognition events, applies deterministic access rules, records decisions and provides an operator console for review and configuration.

## Components

- **Cerberus Core** (`backend/`) - Django application, REST API, operator console, access decisions and audit trail.
- **Janus** (`janus/`) - internal ANPR/OCR recognition service; it provides recognition data but never makes an access decision.
- **PostgreSQL** - persistent application data.
- **Redis** - cache and Celery broker/result backend.
- **Celery worker** - asynchronous tasks.
- **Nginx** - public reverse proxy and static-file server.

The application network is private: only Nginx publishes a host port.

## Run locally

Prerequisites: Docker Desktop with Docker Compose v2.22 or newer. Python 3.12+ and Poetry are needed only to run tools and tests directly on the host.

1. Optionally copy `.env.example` to `.env` and change local credentials or port values. Do not commit `.env`.
2. Start the development stack with automatic rebuilds when source files change:

   ```bash
   make up
   ```

   On systems without GNU Make, use:

   ```bash
   docker compose up --build --watch
   ```

3. Open `http://localhost:8080/`. It redirects to the operator sign-in page.

To stop the stack, run `make down` or `docker compose down`.

## Local users and demo data

On backend startup the development stack runs migrations, creates static files, creates the optional local users, and seeds demo configuration/events. The process is idempotent: restarting containers does not duplicate the demo records.

| Role | Default username | Default password | Capabilities |
| --- | --- | --- | --- |
| Operator | `operator` | `operator-demo-password` | Views events and all Configuration sections in read-only mode; can process the manual-review queue. |
| Administrator | `admin` | `admin-demo-password` | Full operator-console configuration access. |

The users and demo data are development-only and can be configured in `.env`:

```dotenv
CREATE_DEMO_DATA=true
CREATE_TEST_OPERATOR=true
CREATE_TEST_ADMIN=true
TEST_OPERATOR_USERNAME=operator
TEST_OPERATOR_PASSWORD=operator-demo-password
TEST_ADMIN_USERNAME=admin
TEST_ADMIN_PASSWORD=admin-demo-password
```

Change the passwords before exposing any environment beyond local development.

## Operator console

After sign-in, the console provides:

- event list with filters, a result counter and pagination of 20 events per page;
- a Manual review queue with its event counter in the navigation;
- event detail and an audited **Open** command for manual-review events (the command is queued for the mock controller and does not operate a physical barrier);
- Configuration sections for parking sites, gates, cameras, vehicles, access lists and access rules.

Administrators and managers can create and edit configuration. Operators and read-only users can view the same configuration pages without forms or edit actions.

## Endpoints

All public URLs are served through Nginx on `http://localhost:8080` by default.

| URL | Purpose |
| --- | --- |
| `/` | Redirects to `/operator/login/` |
| `/operator/` | Operator dashboard |
| `/operator/manual-review/` | Manual-review queue |
| `/api/docs/` | Swagger UI for the REST API |
| `/api/schema/` | OpenAPI schema |
| `/healthz` | Nginx health response |

The REST API includes authentication, role management, audit logs, service identity and recognition-event ingestion under `/api/v1/`.

## Development commands

```bash
make install    # install Poetry environments and pre-commit hook
make lint       # Ruff for backend and Janus
make format     # format backend and Janus
make typecheck  # MyPy for backend and Janus
make test       # pytest for backend and Janus
make check      # lint, typecheck, and tests
make logs       # follow Compose logs
```

On Windows without GNU Make, run the corresponding `poetry -C backend ...`, `poetry -C janus ...`, or `docker compose ...` commands directly.

## Repository layout

```text
backend/    Cerberus Core Django application
janus/      Internal recognition service
nginx/      Public edge-proxy configuration
docker/     Shared container-related assets
docs/       Product and engineering documentation
scripts/    Developer and operational scripts
static/     Assets mounted directly by Nginx (favicon)
```
