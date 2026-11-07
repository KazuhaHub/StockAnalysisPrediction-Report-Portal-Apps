# Scheduled Digest reference app

This is the managed reference application for `scheduled-digest.run`. It has an
independent Go backend and a React/Ant Design frontend using the shared Portal
SDK. It is a development fixture; this directory does not enroll a publisher or
publish an image.

## Authority

The signed descriptor requires:

- `background.run`;
- `reports.read`;
- `secrets.use`; and
- `tasks.schedule`.

The required `digest-feed` credential binding completes business setup. A
setup-only (`raw_read`) binding can satisfy that gate without granting network
use. When the administrator also grants optional `network.http`, they can
replace it with a reviewed HTTP binding and exercise the shared reviewed-network
path. The credential value never enters the application.

The backend receives no viewer identity for scheduled work. Portal admits only
the app-bound `scheduled-digest.run` handler and sends the fixed
`POST /v1/tasks/digest` route. The task body binds task and occurrence identity;
the service identity binds the current installation, generation, policy, release,
epoch, lease and resource set.

## Backend

The backend serves:

- `GET /health/ready` for readiness;
- `GET /v1/digest` for current-viewer status; and
- `POST /v1/tasks/digest` for the fixed background handler.

Digest runs are persisted under `/data/digest-state.json`. Replaying the same
task and canonical payload returns the original digest with `duplicate:true`.
Changing the payload or occurrence under the same task identity is refused.
When the data mount is read-only, the backend keeps bounded in-memory state so
the development fixture can still become ready.

## Checks

```sh
go test ./apps/scheduled-digest/service/...
npm run typecheck --workspace=apps/scheduled-digest/frontend
npm test --workspace=apps/scheduled-digest/frontend
python3 scripts/plugin-standard.py
python3 scripts/build-app-v2.py scheduled-digest
```

The descriptor placeholder image and frontend digest are not publication
evidence. A native run must build and install the exact image, exercise a real
task, and record the resulting package and image digests.
