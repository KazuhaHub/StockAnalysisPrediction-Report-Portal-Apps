const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  safeState,
  percentage,
  monitorHint,
  compatibleBackend,
  REQUIRED_CAPABILITIES,
} = require("../src/contracts.cjs");
test("unrecognized and stale states never render healthy", () => {
  assert.equal(safeState("new-state"), "unknown");
  assert.equal(safeState("operational", true), "unknown");
  assert.equal(safeState("outage"), "outage");
});
test("zero coverage is not a promise of perfect uptime", () => {
  assert.equal(percentage(0, 0), null);
  assert.equal(percentage(9, 10), "90.00%");
  assert.equal(percentage(11, 10), null);
});
test("unsupported billing has a setup explanation and never implies zero credit", () => {
  assert.equal(
    monitorHint({ outcome: "unsupported", reason_code: "billing_unsupported" }),
    "billingUnsupportedHint",
  );
  assert.equal(
    monitorHint({
      outcome: "unknown",
      reason_code: "billing_permission_required",
    }),
    "billingPermissionHint",
  );
  assert.equal(
    monitorHint({ outcome: "unknown", reason_code: "billing_site_mismatch" }),
    "billingSiteHint",
  );
  assert.equal(
    monitorHint({
      outcome: "success",
      reason_code: "balance_read",
      stale: true,
    }),
    "staleHint",
  );
  assert.equal(monitorHint({ reason_code: "unexpected-upstream-text" }), "");
  assert.equal(
    monitorHint({ reason_code: "local_socket_unavailable" }),
    "postgresSocketHint",
  );
});

test("backend capability handshake refuses old or malformed service replies", () => {
  assert.equal(compatibleBackend({ admin: true }), false);
  assert.equal(
    compatibleBackend({ api_version: 2, capabilities: REQUIRED_CAPABILITIES }),
    false,
  );
  assert.equal(compatibleBackend({ api_version: 1, capabilities: [] }), false);
  assert.equal(
    compatibleBackend({ api_version: 1, capabilities: REQUIRED_CAPABILITIES }),
    true,
  );
  assert.equal(
    compatibleBackend({
      api_version: 1,
      capabilities: REQUIRED_CAPABILITIES.filter(
        (value) => value !== "status.postgres-unix.v1",
      ),
    }),
    false,
  );
});
