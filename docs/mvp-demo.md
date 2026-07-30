# Cerberus MVP demonstration

The development stack seeds a parking site, entry camera, vehicles, access lists, rules and three
events. The supported outcomes are deterministic: Allow, Deny and Manual review.

## Operator-console flow

1. Sign in as a Manager or Administrator.
2. Open **Demo submit** and select **North Entry Camera**.
3. Submit one of the following plates:
   - `A 123 BC 77` — Allow;
   - `B 456 DE 77` — Deny;
   - `X 000 XX 77` — Manual review.
4. Open the event detail. For the Manual review scenario, request **Open barrier** with a reason.
5. Verify the event decision, audit history and mock barrier command status.

The demo submitter exists only when `DEMO_EVENT_SUBMISSION_ENABLED=true`; it is disabled by the
base and production settings.

## Swagger flow

Open `/api/docs/`, authorize the request with these development-only headers, then call
`POST /api/v1/recognition-events`:

```text
X-Service-Client: janus-demo
X-Service-Key: janus-demo-key
```

Use `demo-entry-camera` and a new UUID for `recognition_request_id`. The demo credential is
created only when `CREATE_DEMO_DATA=true`; change its values in `.env` before exposing a
non-local environment.

## Screenshot checklist

Capture these screens after starting the stack:

1. Swagger request and response for an Allow decision.
2. Manual review event detail with the queued barrier command.
3. Activity log with the Configuration changes tab.
4. Barrier control with an active independent command.
