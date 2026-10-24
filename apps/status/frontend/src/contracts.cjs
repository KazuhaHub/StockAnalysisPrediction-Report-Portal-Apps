(function () {
  function proxyRequest(method, path, body) {
    if (!['GET', 'POST', 'PUT', 'DELETE'].includes(method) || typeof path !== 'string' || !path.startsWith('/v1/') || path.length > 2048 || /[\s#\\]/.test(path)) throw new Error('Invalid extension request')
    let decoded = path
    try { for (let i = 0; i < 3; i++) decoded = decodeURIComponent(decoded) } catch { throw new Error('Invalid extension path') }
    if (decoded.includes('..') || decoded.includes('//') || (method === 'GET' && body !== undefined)) throw new Error('Invalid extension path or GET body')
    const inner = { method, path }
    if (body !== undefined) inner.body = body
    return { method: 'POST', path: '/api/v1/extensions/status/request', body: inner }
  }
  function safeState(state, stale) { return !stale && ['operational', 'degraded', 'outage', 'maintenance', 'paused'].includes(state) ? state : 'unknown' }
  function selectLocale(language) { return /^zh-(TW|HK|Hant)/i.test(language) ? 'zh-TW' : /^zh/i.test(language) ? 'zh-CN' : 'en-US' }
  function percentage(value, total) { return total > 0 && value >= 0 && value <= total ? (value / total * 100).toFixed(2) + '%' : null }
  function monitorHint(monitor) {
    if (monitor.stale) return 'staleHint'
    return ({ billing_unsupported: 'billingUnsupportedHint', billing_permission_required: 'billingPermissionHint', billing_site_mismatch: 'billingSiteHint', currency_unavailable: 'currencyHint', authentication_failed: 'authenticationHint', observer_unavailable: 'observerHint' })[monitor.reason_code] || ''
  }
  function requestErrorKey(status) {
    return ({ 400: 'invalidConfiguration', 401: 'accessDenied', 403: 'accessDenied', 404: 'itemUnavailable', 409: 'configurationConflict', 422: 'invalidConfiguration', 429: 'requestBusy' })[status] || 'unavailable'
  }
  const REQUIRED_CAPABILITIES = Object.freeze(['status.components.v1', 'status.history.v2', 'status.export.v1', 'status.retention.v1'])
  function compatibleBackend(reply) { return reply?.api_version === 1 && Array.isArray(reply.capabilities) && REQUIRED_CAPABILITIES.every(capability => reply.capabilities.includes(capability)) }
  const contracts = Object.freeze({ proxyRequest, safeState, selectLocale, percentage, monitorHint, requestErrorKey, compatibleBackend, REQUIRED_CAPABILITIES })
  globalThis.StatusContracts = contracts
  if (typeof module !== 'undefined') module.exports = contracts
})()
