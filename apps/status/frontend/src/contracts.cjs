(function () {
  function safeState(state, stale) {
    return !stale &&
      ["operational", "degraded", "outage", "maintenance", "paused"].includes(
        state,
      )
      ? state
      : "unknown";
  }
  function percentage(value, total) {
    return total > 0 && value >= 0 && value <= total
      ? ((value / total) * 100).toFixed(2) + "%"
      : null;
  }
  function monitorHint(monitor) {
    if (monitor.stale) return "staleHint";
    return (
      {
        billing_unsupported: "billingUnsupportedHint",
        billing_permission_required: "billingPermissionHint",
        billing_site_mismatch: "billingSiteHint",
        currency_unavailable: "currencyHint",
        authentication_failed: "authenticationHint",
        observer_unavailable: "observerHint",
        local_socket_unavailable: "postgresSocketHint",
      }[monitor.reason_code] || ""
    );
  }
  const REQUIRED_CAPABILITIES = Object.freeze([
    "status.components.v1",
    "status.history.v2",
    "status.export.v1",
    "status.retention.v1",
    "status.postgres-unix.v1",
  ]);
  function compatibleBackend(reply) {
    return (
      reply?.api_version === 1 &&
      Array.isArray(reply.capabilities) &&
      REQUIRED_CAPABILITIES.every((capability) =>
        reply.capabilities.includes(capability),
      )
    );
  }
  const contracts = Object.freeze({
    safeState,
    percentage,
    monitorHint,
    compatibleBackend,
    REQUIRED_CAPABILITIES,
  });
  if (typeof module !== "undefined") module.exports = contracts;
})();
