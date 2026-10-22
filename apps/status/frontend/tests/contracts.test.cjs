const { test } = require('node:test')
const assert = require('node:assert/strict')
const { proxyRequest, safeState, selectLocale, percentage, monitorHint, requestErrorKey } = require('../src/contracts.cjs')
test('private requests use the exact installed-app bridge without caller authority', () => {
  assert.deepEqual(proxyRequest('GET', '/v1/components'), { method: 'POST', path: '/api/v1/extensions/status/request', body: { method: 'GET', path: '/v1/components' } })
  for (const path of ['https://other/v1/x', '/api/admin/users', '/v1/../x', '/v1/%252e%252e/x', '//other/v1/x']) assert.throws(() => proxyRequest('GET', path))
  assert.throws(() => proxyRequest('GET', '/v1/components', { role: 'admin' }))
})
test('unrecognized and stale states never render healthy', () => {
  assert.equal(safeState('new-state'), 'unknown')
  assert.equal(safeState('operational', true), 'unknown')
  assert.equal(safeState('outage'), 'outage')
})
test('zero coverage is not a promise of perfect uptime', () => {
  assert.equal(percentage(0, 0), null)
  assert.equal(percentage(9, 10), '90.00%')
  assert.equal(percentage(11, 10), null)
})
test('all supported user languages have deterministic fallback', () => {
  assert.equal(selectLocale('zh-HK'), 'zh-TW')
  assert.equal(selectLocale('zh-SG'), 'zh-CN')
  assert.equal(selectLocale('fr-FR'), 'en-US')
})

test('unsupported billing has a setup explanation and never implies zero credit', () => {
  assert.equal(monitorHint({ outcome: 'unsupported', reason_code: 'billing_unsupported' }), 'billingUnsupportedHint')
  assert.equal(monitorHint({ outcome: 'unknown', reason_code: 'billing_permission_required' }), 'billingPermissionHint')
  assert.equal(monitorHint({ outcome: 'unknown', reason_code: 'billing_site_mismatch' }), 'billingSiteHint')
  assert.equal(monitorHint({ outcome: 'success', reason_code: 'balance_read', stale: true }), 'staleHint')
  assert.equal(monitorHint({ reason_code: 'unexpected-upstream-text' }), '')
})

test('safe backend status selects actionable localized errors', () => {
  assert.equal(requestErrorKey(400), 'invalidConfiguration')
  assert.equal(requestErrorKey(409), 'configurationConflict')
  assert.equal(requestErrorKey(429), 'requestBusy')
  assert.equal(requestErrorKey(403), 'accessDenied')
  assert.equal(requestErrorKey(500), 'unavailable')
})
