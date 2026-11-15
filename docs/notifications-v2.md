# Application notification publishing

`useAppNotifications()` is the foreground SDK entry for the reviewed
`notifications.publish` capability. It captures a bounded event in Portal's
existing notification service; it does not select recipients, channels, routes
or destinations.

```tsx
import { useAppNotifications } from "@portal-app/sdk/root-v2";

function DigestControls() {
  const notifications = useAppNotifications();
  return (
    <button
      disabled={!notifications.ready}
      onClick={() => {
        void notifications.publish({
          occurrenceId: "digest:2026-11-02",
          title: "Daily digest",
          message: "Three reports are ready.",
          severity: "info",
        });
      }}
    >
      Publish digest notice
    </button>
  );
}
```

The occurrence ID is a stable idempotency key. Repeating it with identical
content returns the existing event ID; changing title, message or severity
under the same key fails with `conflict`. A full per-source capacity fails with
`capacity`. Do not generate a fresh occurrence ID merely because a reply was
lost.

The SDK admits one publication at a time. The hook becomes unavailable when the
host does not advertise the exact current grant or when the presentation is
retiring. Errors never include recipient or credential metadata.

