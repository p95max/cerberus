# Cerberus

Cerberus is a parking and vehicle access-control platform. It accepts vehicle-recognition events, applies deterministic access rules, records decisions and provides an operator console for review and configuration.

## Components

- **Cerberus Core** (`backend/`) - Django application, REST API, operator console, access decisions and audit trail.
- **Janus** (`janus/`) - internal ANPR/OCR recognition service; it provides recognition data but never makes an access decision.
- **PostgreSQL** - persistent application data.
- **Redis** - cache and Celery broker/result backend.
- **Celery worker** - asynchronous tasks.
- **Celery Beat** - schedules the optional recognition-data retention task.
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

## Tests

The development backend image includes the test dependencies. After changing the Dockerfile or
dependencies, rebuild it once, then run the test suite inside the container:

```bash
docker compose up --build -d backend
docker compose exec backend pytest
```

The command uses the isolated SQLite test settings (`config.settings.test`), not the running
development database.

## Local users and demo data

On backend startup the development stack runs migrations, creates static files, creates the optional local users, and seeds demo configuration/events. The process is idempotent: restarting containers does not duplicate the demo records.

| Role | Default username | Default password | Capabilities |
| --- | --- | --- | --- |
| Operator | `operator` | `operator-demo-password` | Works with events, manual review and Barrier control; views operational Configuration in read-only mode. |
| Manager | `manager` | `manager-demo-password` | Operator capabilities plus Configuration changes (except Data retention) and Activity log access. |
| Administrator | `admin` | `admin-demo-password` | Full Configuration access, Data retention, Activity log JSON export and Django Admin. |

The users and demo data are development-only and can be configured in `.env`:

```dotenv
CREATE_DEMO_DATA=true
CREATE_TEST_OPERATOR=true
CREATE_TEST_MANAGER=true
CREATE_TEST_ADMIN=true
DJANGO_ADMIN_URL=admin/
DEMO_EVENT_SUBMISSION_ENABLED=true
DEMO_SERVICE_CLIENT_ID=janus-demo
DEMO_SERVICE_KEY=janus-demo-key
TEST_OPERATOR_USERNAME=operator
TEST_OPERATOR_PASSWORD=operator-demo-password
TEST_MANAGER_USERNAME=manager
TEST_MANAGER_PASSWORD=manager-demo-password
TEST_ADMIN_USERNAME=admin
TEST_ADMIN_PASSWORD=admin-demo-password
```

Change the passwords before exposing any environment beyond local development.
`TEST_ADMIN_*` creates a Django superuser too. Its Django Admin path is configured by
`DJANGO_ADMIN_URL` (default: `admin/`).

## Recognition-data retention

Retention is enabled by default in the local stack and runs hourly. Only an Administrator can open and configure **Configuration → Data retention**. Image metadata can be cleared after 30 days, full recognition events (and their decisions and queued barrier commands) can be deleted after 180 days, and aggregate cleanup-audit records can be retained for 730 days. Ordinary security-audit records are not deleted by this task.

Configure or disable it in `.env`:

```dotenv
RECOGNITION_RETENTION_ENABLED=true
RECOGNITION_IMAGE_METADATA_RETENTION_ENABLED=true
RECOGNITION_IMAGE_METADATA_RETENTION_DAYS=30
RECOGNITION_EVENT_RETENTION_ENABLED=true
RECOGNITION_EVENT_RETENTION_DAYS=180
RECOGNITION_AGGREGATE_AUDIT_RETENTION_ENABLED=true
RECOGNITION_AGGREGATE_AUDIT_RETENTION_DAYS=730
RECOGNITION_PURGE_INTERVAL_SECONDS=3600
```

These values seed the initial policy when it is first opened. After saving **Configuration → Data retention**, the values in the console take precedence. Set `RECOGNITION_RETENTION_ENABLED=false` to create an initially disabled policy, or change individual `*_ENABLED` defaults.

## Operator console

After sign-in, the console provides:

- event list with filters, a result counter and pagination of 20 events per page;
- a Manual review queue with its event counter in the navigation;
- event detail and an audited **Open** command for manual-review events (the command is queued for the mock controller and does not operate a physical barrier);
- Configuration sections for parking sites/objects, gates, cameras, vehicles, access lists and access rules. Each tab explains its purpose; **Access rules** define the Allow/Deny decision for a vehicle at a gate and use priority to resolve conflicts.
- an independent **Barrier control** screen for urgent manual openings without a recognition event, with a reason, optional request number and either an automatic-close delay or an indefinite opening;
- an **Activity log** for Managers and Administrators. It has an **All activity** view and a **Configuration changes** view that records the actor, time, IP, object and before/after values for configuration updates. All seven table columns can be sorted; Administrators can export the filtered log as dated JSON.

Administrators can edit every Configuration section. Managers can edit all operational sections except **Data retention**. Operators and read-only users can view the operational sections without forms or edit actions; **Data retention** is hidden from them and returns 403 on direct access.

The mock barrier automatically closes after 10 seconds by default. Its countdown is shown on the event page and the automatic close is recorded in Audit history. Managers and administrators can change the delay in **Configuration → Barrier control**; `BARRIER_AUTO_CLOSE_SECONDS` in `.env` is only the initial value.

## Endpoints

All public URLs are served through Nginx on `http://localhost:8080` by default.

| URL | Purpose |
| --- | --- |
| `/` | Redirects to `/operator/login/` |
| `/operator/` | Operator dashboard |
| `/operator/manual-review/` | Manual-review queue |
| `/operator/barrier-control/` | Independent manual barrier override |
| `/operator/activity-log/` | Activity log for Managers and Administrators |
| `/admin/` | Django Admin (default; path is set with `DJANGO_ADMIN_URL`) |
| `/api/docs/` | Swagger UI for the REST API |
| `/api/schema/` | OpenAPI schema |
| `/healthz` | Nginx health response |

The REST API includes authentication, role management, audit logs, service identity and recognition-event ingestion under `/api/v1/`.

For the reproducible MVP flow, Swagger request headers and screenshot targets, see
[MVP demonstration](docs/mvp-demo.md). The system and request-flow diagrams are in
[architecture](docs/architecture.md).

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
