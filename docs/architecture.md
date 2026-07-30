# Cerberus MVP architecture

```mermaid
flowchart LR
    Browser[Operator browser] --> Nginx[Nginx]
    Nginx --> Core[Cerberus Core\nDjango + DRF]
    Core --> Postgres[(PostgreSQL)]
    Core --> Redis[(Redis)]
    Core --> Worker[Celery worker]
    Worker --> Mock[Mock barrier controller]
    Janus[Janus recognition service\nfuture integration] -->|authenticated recognition event| Core
```

Cerberus Core is the only component that evaluates access rules and queues barrier commands.
Janus supplies recognition data only; it never decides whether a barrier should open.

## MVP request flow

```mermaid
sequenceDiagram
    participant Client as Swagger / demo form / Janus
    participant Core as Cerberus Core
    participant DB as PostgreSQL
    participant Worker as Celery worker
    participant Barrier as Mock barrier

    Client->>Core: Submit plate recognition event
    Core->>DB: Store event and evaluate deterministic rules
    Core->>DB: Store decision and audit record
    Core-->>Client: allow / deny / manual_review
    Note over Client,Core: Manual review may request an opening
    Core->>DB: Store BarrierCommand and audit record
    Core->>Worker: Queue command
    Worker->>Barrier: Open command
    Barrier-->>Worker: Acknowledged
    Worker->>DB: Store command status and audit record
```
