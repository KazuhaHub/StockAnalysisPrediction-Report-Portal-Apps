const { test, expect, request } = require('@playwright/test')
const { spawn, spawnSync } = require('node:child_process')
const { mkdtempSync, writeFileSync, readFileSync, rmSync } = require('node:fs')
const { tmpdir, networkInterfaces } = require('node:os')
const { join, resolve } = require('node:path')
const { randomBytes } = require('node:crypto')
const net = require('node:net')
const http = require('node:http')
const portalBinary = process.env.PORTAL_BINARY
const statusBinary = process.env.STATUS_BINARY
let folder, portal, service, base, statusBase, adminAPI, groupA, groupB, componentA, componentB
const processes = [], contexts = []
const password = 'Fixture-Only-Password-1022'
function freePort() { return new Promise((resolve, reject) => { const server = net.createServer(); server.once('error', reject); server.listen(0, '0.0.0.0', () => { const port = server.address().port; server.close(() => resolve(port)) }) }) }
function fixtureEnvironment(overrides = {}) { return { ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('RP_'))), ...overrides } }
function launch(binary, args, env) { const process = spawn(binary, args, { cwd: folder, env: fixtureEnvironment(env), stdio: ['ignore', 'pipe', 'pipe'] }); let output = ''; process.stdout.on('data', chunk => { output += chunk }); process.stderr.on('data', chunk => { output += chunk }); process.output = () => output; processes.push(process); return process }
async function ready(url, process) { const deadline = Date.now() + 30000; while (Date.now() < deadline) { if (process.exitCode !== null) throw new Error('Fixture process exited: ' + process.output()); try { const response = await fetch(url); if (response.ok) return } catch {} await new Promise(r => setTimeout(r, 100)) } throw new Error('Fixture readiness timed out') }
async function body(response) { const text = await response.text(); if (!response.ok()) throw new Error('Fixture request failed (' + response.status() + '): ' + text); return JSON.parse(text) }
async function login(username) {
  const context = await request.newContext({ baseURL: base }); contexts.push(context)
  await body(await context.post('/api/login', { data: { username, password } }))
  // These fixture accounts have already used this release. Portal's first-use
  // release-note dialog is covered by Portal tests and would obscure app controls.
  const version = await body(await context.get('/api/version'))
  await body(await context.post('/api/me/version-use', { data: { version: version.version } }))
  return context
}
async function proxy(api, method, path, input) { const token = await body(await api.post('/api/apps/status/token')); return body(await api.post('/api/v1/extensions/status/request', { headers: { Authorization: 'Bearer ' + token.token }, data: { method, path, ...(input === undefined ? {} : { body: input }) } })) }

async function choose(frame, name, label, popup = frame) {
  await frame.getByRole('combobox', { name, exact: true }).click()
  await popup.getByRole('option', { name: label, exact: true }).click()
}
async function openStatus(page) {
  await page.addLocatorHandler(page.locator('.rp-login-activity-notice'), async notice => { await notice.getByRole('button', { name: 'Close', exact: true }).click() })
  await page.goto(base + '/apps/x/status')
  const loginNotice = page.locator('.rp-login-activity-notice')
  if (await loginNotice.isVisible()) await loginNotice.getByRole('button', { name: 'Close', exact: true }).click()
}
async function next(frame) { await frame.getByRole('button', { name: 'Next', exact: true }).click() }
test.beforeAll(async () => {
  test.skip(!portalBinary || !statusBinary, 'PORTAL_BINARY and STATUS_BINARY are required for real integration acceptance')
  folder = mkdtempSync(join(tmpdir(), 'status-acceptance-'))
  const address = Object.values(networkInterfaces()).flat().find(i => i.family === 'IPv4' && !i.internal && /^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/.test(i.address))?.address
  if (!address) throw new Error('A private interface is required; loopback exceptions are deliberately not enabled')
  const port = await freePort(), servicePort = await freePort()
  base = 'http://127.0.0.1:' + port; statusBase = 'http://127.0.0.1:' + servicePort
  const config = join(folder, 'portal.yaml')
  writeFileSync(config, 'listen: "127.0.0.1:' + port + '"\nsecret_key: "' + randomBytes(32).toString('hex') + '"\ndb_driver: "sqlite"\ndb_path: "' + join(folder, 'portal.db') + '"\n', { mode: 0o600 })
  const seeded = spawnSync(portalBinary, ['adduser', 'admin', password, 'admin'], { cwd: folder, env: fixtureEnvironment({ RP_CONFIG: config }), encoding: 'utf8' })
  if (seeded.status !== 0) throw new Error('Portal fixture account setup failed: ' + seeded.stderr)
  portal = launch(portalBinary, [], { RP_CONFIG: config }); await ready(base + '/healthz', portal)
  adminAPI = await login('admin')
  const bundle = readFileSync(resolve(__dirname, '../../../dist/status', JSON.parse(readFileSync(resolve(__dirname, '../app.json'), 'utf8')).version, 'status.zip'))
  await body(await adminAPI.post('/api/admin/apps/install', { multipart: { bundle: { name: 'status.zip', mimeType: 'application/zip', buffer: bundle } } }))
  const signingKey = randomBytes(32).toString('base64')
  const registration = await body(await adminAPI.put('/api/admin/apps/status/backend', { data: { revision: 0, label: 'Status fixture', base_url: 'http://' + address + ':' + servicePort, audience: 'status', enabled: true, key_id: 'fixture-key', signing_key: signingKey, policy: { version: 1, plain_http: true, networks: [address + '/32'], ports: [servicePort], routes: ['GET', 'POST', 'PUT', 'DELETE'].map(method => ({ method, prefix: '/v1/' })) } } }))
  writeFileSync(join(folder, 'pairing.json'), JSON.stringify({ issuer: registration.issuer, audience: registration.audience, app_id: 'status', instance_id: registration.instance_id, key_id: 'fixture-key', signing_key: signingKey }), { mode: 0o600 })
  writeFileSync(join(folder, 'storage.key'), randomBytes(32).toString('base64'), { mode: 0o600 })
  service = launch(statusBinary, ['serve', '-listen', '0.0.0.0:' + servicePort, '-database', join(folder, 'status.db'), '-storage-key-file', join(folder, 'storage.key'), '-pairing-file', join(folder, 'pairing.json')])
  await ready(statusBase + '/healthz', service)
  await proxy(adminAPI, 'PUT', '/v1/manage/settings', { public_enabled: false, probes_paused: true, outbox_paused: true, portal_url: '', portal_networks: [] })
  groupA = (await body(await adminAPI.post('/api/admin/groups', { data: { name: 'Operations A' } }))).id
  groupB = (await body(await adminAPI.post('/api/admin/groups', { data: { name: 'Operations B' } }))).id
  for (const [username, group] of [['viewer-a', groupA], ['viewer-b', groupB]]) await body(await adminAPI.post('/api/admin/users', { data: { username, password, role: 'user', primary_group: group } }))
  const token = await body(await adminAPI.post('/api/apps/status/token'))
  const directory = await body(await adminAPI.get('/api/v1/extensions/status/principals?kind=ou', { headers: { Authorization: 'Bearer ' + token.token } }))
  const principal = label => directory.items.find(item => item.label === label).principal
  const create = async (label, grant, published) => (await proxy(adminAPI, 'PUT', '/v1/manage/components', { label, enabled: true, public_enabled: published, public_label: published ? 'Public report storage' : '', revision: 0, grants: [{ principal: grant, permission: 'read' }], monitors: [] })).item
  componentA = await create('Private operations A', principal('Operations A'), true)
  componentB = await create('Private operations B', principal('Operations B'), false)
})
test.afterAll(async () => {
  for (const context of contexts) await context.dispose()
  for (const process of processes.reverse()) { if (process.exitCode === null) { process.kill('SIGTERM'); await Promise.race([new Promise(r => process.once('exit', r)), new Promise(r => setTimeout(r, 4000))]); if (process.exitCode === null) process.kill('SIGKILL') } }
  if (folder) rmSync(folder, { recursive: true, force: true })
})

test('canonical public market downloads an app only after permission confirmation', async ({ browser }) => {
  const canonical = 'https://raw.githubusercontent.com/KazuhaHub/StockAnalysisPrediction-Report-Portal-Apps/main/index.json'
  await body(await adminAPI.post('/api/admin/apps/market/index', { data: { index_url: canonical } }))
  const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US' })
  try {
    const page = await context.newPage(), installs = []
    page.on('request', request => { if (new URL(request.url()).pathname === '/api/admin/apps/market/install') installs.push(request) })
    await page.goto(base + '/manage/apps')
    await page.getByRole('button', { name: /Fetch from GitHub/ }).click()
    await expect(page.getByRole('textbox', { name: 'App market index URL', exact: true })).toHaveValue(canonical)
    const row = page.getByRole('row').filter({ hasText: 'Symbols demo' })
    await row.getByRole('button', { name: /Install$/ }).click()
    let dialog = page.getByRole('dialog')
    await expect(dialog.getByText('Read reports and stock data (read-only)', { exact: true })).toBeVisible()
    expect(installs).toHaveLength(0)
    expect((await body(await adminAPI.get('/api/apps'))).apps.some(item => item.id === 'demo-symbols')).toBe(false)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await expect(dialog).toBeHidden()
    expect(installs).toHaveLength(0)
    await row.getByRole('button', { name: /Install$/ }).click()
    dialog = page.getByRole('dialog')
    await dialog.getByRole('button', { name: 'Grant & install', exact: true }).click()
    await expect(dialog).toBeHidden()
    await expect.poll(async () => (await body(await adminAPI.get('/api/apps'))).apps.some(item => item.id === 'demo-symbols')).toBe(true)
    expect(installs).toHaveLength(1)
    const installed = (await body(await adminAPI.get('/api/apps'))).apps.find(item => item.id === 'demo-symbols')
    expect(installed.scopes).toEqual(['query'])
    await page.goto(base + '/apps/x/demo-symbols')
    const frame = page.frameLocator('iframe')
    await expect(frame.getByRole('heading', { name: /Stocks with reports/ })).toBeVisible()
    await expect(frame.getByText('No matching stocks.', { exact: true })).toBeVisible()
  } finally {
    await context.close()
    await body(await adminAPI.delete('/api/admin/apps/demo-symbols'))
    await body(await adminAPI.post('/api/admin/apps/market/index', { data: { index_url: '' } }))
  }
})

test('real Portal bridge shows each current OU only its permitted component', async ({ browser }) => {
  for (const [username, visible, hidden] of [['viewer-a', 'Private operations A', 'Private operations B'], ['viewer-b', 'Private operations B', 'Private operations A']]) {
    const api = await login(username), context = await browser.newContext({ storageState: await api.storageState(), locale: 'en-US' }), page = await context.newPage()
    await openStatus(page)
    const frame = page.frameLocator('iframe')
    await expect(frame.getByRole('heading', { name: visible, exact: true })).toBeVisible()
    await expect(frame.getByRole('heading', { name: hidden, exact: true })).toHaveCount(0)
    await expect(frame.getByRole('button', { name: 'Manage', exact: true })).toHaveCount(0)
    await context.close()
  }
  await body(await adminAPI.put('/api/admin/users/viewer-a', { data: { primary_group: groupB } }))
  const changed = await login('viewer-a'), response = await proxy(changed, 'GET', '/v1/components')
  expect(response.items.map(c => c.label)).toEqual(['Private operations B'])
})

test('administrator can create a component and multiple monitors through the installed UI', async ({ browser }) => {
  const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US' }), page = await context.newPage()
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  await openStatus(page)
  const frame = page.frameLocator('iframe')
  await frame.getByRole('button', { name: 'Manage', exact: true }).click()
  await frame.getByRole('button', { name: 'New component', exact: true }).click()
  await frame.getByLabel('Internal label', { exact: true }).fill('UI configured service')
  await frame.getByLabel('Enabled', { exact: true }).check()
  await next(frame)
  let monitors = frame.locator('fieldset')
  await monitors.nth(0).getByLabel('Internal label', { exact: true }).fill('First readiness')
  await monitors.nth(0).getByLabel('Target URL', { exact: true }).fill('https://first.invalid/health')
  await monitors.nth(0).getByText('Advanced options', { exact: true }).click()
  await monitors.nth(0).getByLabel('Expected HTTP status (optional)', { exact: true }).fill('204')
  await frame.getByRole('button', { name: 'Add monitor', exact: true }).click()
  await monitors.nth(1).getByLabel('Internal label', { exact: true }).fill('Second readiness')
  await monitors.nth(1).getByLabel('Target URL', { exact: true }).fill('https://second.invalid/health')
  await monitors.nth(1).getByLabel('Target URL', { exact: true }).fill('invalid-target')
  await next(frame)
  await expect(frame.locator('[role="dialog"] [role="alert"]')).toBeVisible()
  await expect(monitors).toHaveCount(2)
  await monitors.nth(1).getByLabel('Target URL', { exact: true }).fill('https://second.invalid/health')
  await next(frame)
  await frame.getByRole('button', { name: 'Load users and organizational units', exact: true }).click()
  await expect(frame.getByRole('button', { name: 'Save', exact: true })).toBeEnabled()
  await frame.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(frame.getByRole('dialog')).toHaveCount(0)
  await expect(frame.getByRole('row').filter({ hasText: 'UI configured service' })).toBeVisible()
  expect(errors).toEqual([])
  const all = await proxy(adminAPI, 'GET', '/v1/manage/components')
  const saved = all.items.find(c => c.label === 'UI configured service')
  expect(saved.monitors.map(m => m.label)).toEqual(expect.arrayContaining(['First readiness', 'Second readiness']))
  expect(saved.monitors).toHaveLength(2)
  expect(saved.monitors.find(m => m.label === 'First readiness').config.expected_status).toBe(204)
  const editorCard = frame.getByRole('row').filter({ hasText: 'UI configured service' })
  await editorCard.getByRole('button', { name: 'Edit', exact: true }).click()
  await next(frame)
  await expect(frame.getByRole('button', { name: 'Request a check', exact: true })).toHaveCount(2)
  await frame.getByRole('button', { name: 'Request a check', exact: true }).first().click()
  await expect(frame.locator('[role="dialog"] [role="alert"]')).toBeVisible()
  const paused = await proxy(adminAPI, 'GET', '/v1/manage/operations')
  expect(paused.settings.probes_paused).toBe(true)
  await frame.getByRole('button', { name: 'Cancel', exact: true }).click()
  await frame.getByRole('button', { name: 'Manage', exact: true }).click()
  const serviceCard = frame.locator('article').filter({ has: frame.getByRole('heading', { name: 'UI configured service', exact: true }) })
  await serviceCard.getByRole('button', { name: 'Uptime history', exact: true }).click()
  await expect(frame.locator('.history-strip [role="img"]').first()).toBeVisible()
  await expect(frame.getByText('No eligible observed time', { exact: true }).first()).toBeVisible()
  await frame.getByRole('button', { name: 'Export component JSON', exact: true }).click()
  const snapshot = JSON.parse(await frame.getByLabel('Export component JSON', { exact: true }).inputValue())
  expect(snapshot.component.label).toBe('UI configured service')
  expect(JSON.stringify(snapshot)).not.toContain('second.invalid')
  expect(snapshot.version).toBe(1)
  await context.close()
})

test('administrator configures an explicit local PostgreSQL socket without retaining network destinations', async ({ browser }) => {
  const credential = (await proxy(adminAPI, 'PUT', '/v1/manage/credentials', { kind: 'postgres', label: 'Local database fixture', revision: 0, secret: { username: 'read_fixture', password: 'fixture-only' } })).item
  const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US' })
  try {
    const page = await context.newPage(); await openStatus(page)
    const frame = page.frameLocator('iframe')
    await frame.getByRole('button', { name: 'Manage', exact: true }).click()
    await frame.getByRole('button', { name: 'New component', exact: true }).click()
    await frame.getByLabel('Internal label', { exact: true }).fill('Local database component')
    await next(frame)
    const monitor = frame.locator('fieldset').last()
    await monitor.getByLabel('Internal label', { exact: true }).fill('Socket readiness')
    await choose(monitor, 'Check type', 'PostgreSQL SELECT 1', frame)
    await choose(monitor, 'Saved credential', 'Local database fixture', frame)
    await choose(monitor, 'PostgreSQL connection', 'Local Unix socket', frame)
    await expect(monitor.getByLabel('Database host', { exact: true })).toHaveCount(0)
    await monitor.getByLabel('Database name', { exact: true }).fill('fixture')
    await next(frame)
    await frame.getByRole('button', { name: 'Save', exact: true }).click()
    const card = frame.getByRole('row').filter({ hasText: 'Local database component' })
    await card.getByRole('button', { name: 'Edit', exact: true }).click()
    await next(frame)
    await expect(monitor.getByRole('combobox', { name: 'PostgreSQL connection', exact: true })).toBeVisible()
    await choose(monitor, 'PostgreSQL connection', 'Network with verified TLS', frame)
    await monitor.getByLabel('Database host', { exact: true }).fill('database.internal.example')
    await monitor.getByText('Advanced options', { exact: true }).click()
    await monitor.getByLabel('Allowed private CIDRs (one per line)', { exact: true }).fill('10.0.0.0/8')
    await choose(monitor, 'PostgreSQL connection', 'Local Unix socket', frame)
    await next(frame)
    await frame.getByRole('button', { name: 'Save', exact: true }).click()
    // The existing card stays visible while saving. Wait for the completed save
    // and refresh before an independent request uses the bounded proxy capacity.
    await expect(frame.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0)
    await expect(frame.locator('main.status-app')).not.toHaveAttribute('aria-busy', 'true')
    await expect(card).toBeVisible()
    const saved = (await proxy(adminAPI, 'GET', '/v1/manage/components')).items.find(c => c.label === 'Local database component').monitors[0]
    expect(saved.config.postgres_transport).toBe('unix')
    expect(saved.config.host).toBeUndefined()
    expect(saved.config.networks).toBeUndefined()
    expect(saved.config.port).toBe(5432)
    expect((await proxy(adminAPI, 'GET', '/v1/manage/operations')).settings.probes_paused).toBe(true)
  } finally { await context.close() }
})

test('public prefix projection remains closed until enabled and excludes private labels', async ({ browser }) => {
  expect((await fetch(statusBase + '/')).status).toBe(404)
  await proxy(adminAPI, 'PUT', '/v1/manage/settings', { public_enabled: true, probes_paused: true, outbox_paused: true, portal_url: '', portal_networks: [] })
  const page = await browser.newPage()
  await page.route('**/status/**', async route => {
    const url = new URL(route.request().url()), target = statusBase + '/' + url.pathname.split('/status/')[1] + url.search
    const response = await route.fetch({ url: target }); await route.fulfill({ response })
  })
  await page.goto(statusBase + '/status/')
  await expect(page.getByRole('heading', { name: 'Public report storage', exact: true })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Components', exact: true })).toHaveCount(0)
  const publicPage = await (await fetch(statusBase + '/public/v1/status?limit=1&offset=0')).json()
  expect(publicPage.total).toBe(1)
  expect(publicPage.limit).toBe(1)
  await expect(page.getByText('Private operations A', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Private operations B', { exact: true })).toHaveCount(0)
  expect(await page.locator('body').innerText()).not.toContain('portal_url')
  await page.getByRole('button', { name: 'Uptime history', exact: true }).click()
  await expect(page.getByText('No eligible observed time', { exact: true })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.close()
})

test('two component publishers route only to their configured OU and deduplicate retries', async () => {
  const inbox = (await body(await adminAPI.post('/api/admin/notifications/channels', { data: { label: 'Status fixture inbox', adapter: 'inbox', enabled: true } }))).channel
  const fixtures = []
  for (const [component, group, username] of [[componentA, groupA, 'notice-a'], [componentB, groupB, 'notice-b']]) {
    await body(await adminAPI.post('/api/admin/users', { data: { username, password, role: 'user', primary_group: group } }))
    const token = (await body(await adminAPI.post('/api/admin/tokens', { data: { name: 'Status fixture publisher', scope: 'notify:status-' + component.id } }))).token
    const event = 'extension.service.status-' + component.id + '.notice'
    await body(await adminAPI.post('/api/admin/notifications/routes', { data: { label: 'Status fixture audience', channel_id: inbox.id, events: [event], recipient_mode: 'grant', enabled: true, grants: ['g:' + group] } }))
    const publication = { occurrence_id: 'status:' + component.id + ':fixture:1', title: 'Service status changed', message: 'Component ' + component.id + ': outage', severity: 'error' }
    const publish = data => adminAPI.post('/api/v1/notifications', { headers: { Authorization: 'Bearer ' + token }, data })
    const first = await body(await publish(publication)), retry = await body(await publish(publication))
    expect(retry.id).toBe(first.id)
    expect(retry.created).toBe(false)
    expect((await publish({ ...publication, message: 'Changed content' })).status()).toBe(409)
    fixtures.push({ component, event, api: await login(username), eventID: first.id })
  }
  for (const [index, fixture] of fixtures.entries()) {
    const notifications = await body(await fixture.api.get('/api/notifications'))
    expect(notifications.items.filter(item => item.event_type === fixture.event)).toHaveLength(1)
    expect(notifications.items.some(item => item.event_id === fixtures[1 - index].eventID)).toBe(false)
    expect(JSON.stringify(notifications)).not.toContain('Private operations')
    expect(JSON.stringify(notifications)).not.toContain('fixture-publisher-token')
  }
  await body(await adminAPI.put('/api/admin/users/notice-a', { data: { primary_group: groupB } }))
  const moved = await body(await fixtures[0].api.get('/api/notifications'))
  expect(moved.items.some(item => item.event_id === fixtures[0].eventID)).toBe(false)
})

test('operations load within bridge limits and theme and keyboard settings remain usable', async ({ browser }) => {
  const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US', colorScheme: 'dark', viewport: { width: 390, height: 844 } })
  await context.addInitScript(() => { if (window.top === window && location.protocol.startsWith('http')) { try { localStorage.setItem('rp_theme', 'dark') } catch { /* Opaque transient documents have no preference storage. */ } } })
  const page = await context.newPage(), errors = []
  page.on('pageerror', error => errors.push(error.message))
  await openStatus(page)
  const frame = page.frameLocator('iframe')
  await expect(frame.getByRole('heading', { name: 'Service status', exact: true })).toBeVisible()
  await expect.poll(async () => page.frames().find(f => /\/app-assets\//.test(f.url()))?.evaluate(() => document.documentElement.style.colorScheme)).toBe('dark')
  await frame.getByRole('button', { name: 'Manage', exact: true }).click()
  await frame.getByRole('tab', { name: 'Operations', exact: true }).click()
  await frame.getByText('Service settings', { exact: true }).click()
  await expect(frame.getByLabel('Enable reviewed public projection', { exact: true })).toBeVisible()
  await expect(frame.getByLabel('Raw observation retention (days)', { exact: true })).toHaveValue('30')
  await frame.getByLabel('Raw observation retention (days)', { exact: true }).fill('14')
  await frame.getByLabel('History retention (days)', { exact: true }).fill('60')
  await frame.getByRole('button', { name: 'Save', exact: true }).first().click()
  await expect(frame.locator('[role="status"]')).toBeVisible()
  await expect(frame.getByLabel('Raw observation retention (days)', { exact: true })).toHaveValue('14')
  const retention = await proxy(adminAPI, 'GET', '/v1/manage/operations')
  expect(retention.settings.history_retention_days).toBe(60)
  await expect(frame.locator('[role="alert"]')).toHaveCount(0)
  const language = frame.getByRole('combobox', { name: 'Language', exact: true })
  await choose(frame, 'Language', '简体中文')
  await expect(frame.getByRole('heading', { name: '服务状态', exact: true })).toBeVisible()
  await choose(frame, '语言', '繁體中文')
  await expect(frame.getByRole('heading', { name: '服務狀態', exact: true })).toBeVisible()
  await choose(frame, '語言', 'English')
  await frame.getByRole('button', { name: 'Manage', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(frame.getByRole('heading', { name: 'Private operations A', exact: true })).toBeVisible()
  expect(errors).toEqual([])
  await context.close()
})

test('incompatible backend is refused before any component data and can be retried', async ({ browser }) => {
  const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US' }), page = await context.newPage()
  const calls = []
  await page.route('**/api/v1/extensions/status/request', async route => {
    calls.push(route.request().postDataJSON().path)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, admin: true }) })
  })
  await openStatus(page)
  const frame = page.frameLocator('iframe')
  await expect(frame.getByText(/The paired Status backend does not support/)).toBeVisible()
  await expect(frame.getByRole('heading', { name: 'Private operations A', exact: true })).toHaveCount(0)
  await expect(frame.getByRole('button', { name: 'Manage', exact: true })).toHaveCount(0)
  expect(calls).toEqual(['/v1/me'])
  await page.unroute('**/api/v1/extensions/status/request')
  await frame.getByRole('button', { name: 'Refresh', exact: true }).click()
  await expect(frame.getByRole('heading', { name: 'Private operations A', exact: true })).toBeVisible()
  await context.close()
})

test('private and public status pages meet automated accessibility checks', async ({ browser }) => {
  const axeSource = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8')
  async function audit(frame, label) {
    await frame.evaluate(axeSource)
    const violations = await frame.evaluate(async () => (await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'] } })).violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) })))
    expect(violations, label).toEqual([])
  }
  for (const mode of ['light', 'dark']) {
    const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US', colorScheme: mode, viewport: { width: 390, height: 844 } })
    await context.addInitScript(mode => { if (window.top === window && location.protocol.startsWith('http')) { try { localStorage.setItem('rp_theme', mode) } catch { /* Opaque transient documents have no preference storage. */ } } }, mode)
    const page = await context.newPage()
    try {
      await openStatus(page)
      const controls = page.frameLocator('iframe')
      await expect(controls.getByRole('heading', { name: 'Private operations A', exact: true })).toBeVisible()
      const frame = page.frames().find(f => /\/app-assets\//.test(f.url()))
      await audit(frame, mode + ' overview')
      await controls.getByRole('button', { name: 'Manage', exact: true }).click()
      await expect(controls.getByRole('button', { name: 'New component', exact: true })).toBeVisible()
      await audit(frame, mode + ' components')
      await controls.getByRole('button', { name: 'New component', exact: true }).click()
      await expect(controls.getByLabel('Internal label', { exact: true })).toBeVisible()
      await audit(frame, mode + ' component editor')
      await controls.getByRole('button', { name: 'Cancel', exact: true }).click()
      await controls.getByRole('tab', { name: 'Operations', exact: true }).click()
      await controls.getByText('Service settings', { exact: true }).click()
      await expect(controls.getByLabel('Enable reviewed public projection', { exact: true })).toBeVisible()
      await audit(frame, mode + ' operations')
    } finally { await context.close() }
  }
  await proxy(adminAPI, 'PUT', '/v1/manage/settings', { public_enabled: true, probes_paused: true, outbox_paused: true, portal_url: '', portal_networks: [] })
  const context = await browser.newContext({ locale: 'en-US', viewport: { width: 390, height: 844 } })
  try {
    const page = await context.newPage()
    await page.goto(statusBase + '/')
    await expect(page.getByRole('heading', { name: 'Public report storage', exact: true })).toBeVisible()
    await audit(page, 'public overview')
  } finally {
    await context.close()
    await proxy(adminAPI, 'PUT', '/v1/manage/settings', { public_enabled: false, probes_paused: true, outbox_paused: true, portal_url: '', portal_networks: [] })
  }
})

test('narrow layouts keep long labels, enlarged text and keyboard controls usable', async ({ browser }) => {
  const longLabel = 'internal-monitor-'.repeat(8).slice(0, 120)
  await proxy(adminAPI, 'PUT', '/v1/manage/components', { label: longLabel, enabled: true, public_enabled: true, public_label: longLabel, revision: 0, grants: [], monitors: [] })
  const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US', viewport: { width: 320, height: 800 } })
  try {
    const page = await context.newPage()
    await openStatus(page)
    const controls = page.frameLocator('iframe')
    await expect(controls.getByRole('heading', { name: longLabel, exact: true })).toBeVisible()
    const frame = page.frames().find(f => /\/app-assets\//.test(f.url()))
    const reflow = async label => {
      const size = await frame.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }))
      expect(size.scroll, label).toBeLessThanOrEqual(size.width + 1)
    }
    await reflow('private overview at 320 CSS pixels')
    // Enlarge the app's fixed text sizes separately from native browser zoom.
    const enlargedText = 'body { font-size:30px!important } h1 { font-size:48px!important } h2 { font-size:40px!important } h3 { font-size:34px!important } small,pre { font-size:24px!important } textarea { font-size:26px!important }'
    await frame.addStyleTag({ content: enlargedText })
    await reflow('private overview with doubled body text')
    await controls.getByRole('button', { name: 'Manage', exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(controls.getByRole('button', { name: 'New component', exact: true })).toBeVisible()
    await reflow('component list with doubled body text')
    await controls.getByRole('button', { name: 'New component', exact: true }).click()
    await controls.getByLabel('Internal label', { exact: true }).first().fill('Keyboard reflow fixture')
    await page.keyboard.press('Tab')
        await expect(controls.getByLabel('Enabled', { exact: true }).first()).toBeFocused()
    await page.keyboard.press('Space')
    await expect(controls.getByLabel('Enabled', { exact: true }).first()).toBeChecked()
    await reflow('component and monitor editor with doubled body text')
    await page.keyboard.press('Escape')
    await expect(controls.getByRole('dialog')).toHaveCount(0)
      await controls.getByRole('tab', { name: 'Operations', exact: true }).click()
      await controls.getByText('Service settings', { exact: true }).click()
    await expect(controls.getByLabel('Enable reviewed public projection', { exact: true })).toBeVisible()
    await reflow('operations with doubled body text')
    await proxy(adminAPI, 'PUT', '/v1/manage/settings', { public_enabled: true, probes_paused: true, outbox_paused: true, portal_url: '', portal_networks: [] })
    const publicPage = await context.newPage()
    // Preserve the public CSP: apply text enlargement through its same-origin CSS.
    await publicPage.route('**/style.css', async route => {
      const response = await route.fetch()
      await route.fulfill({ response, body: await response.text() + enlargedText })
    })
    await publicPage.goto(statusBase + '/')
    await expect(publicPage.getByRole('heading', { name: longLabel, exact: true })).toBeVisible()
    expect(await publicPage.evaluate(() => getComputedStyle(document.body).fontSize)).toBe('30px')
    expect(await publicPage.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1), 'public overview with doubled body text').toBe(true)
  } finally {
    await context.close()
    await proxy(adminAPI, 'PUT', '/v1/manage/settings', { public_enabled: false, probes_paused: true, outbox_paused: true, portal_url: '', portal_networks: [] })
  }
})

test('recreated accounts cannot reuse a prior direct grant or application token', async () => {
  const username = 'recreated-reader'
  await body(await adminAPI.post('/api/admin/users', { data: { username, password, role: 'user', primary_group: groupA } }))
  const directPrincipal = async () => {
    const token = await body(await adminAPI.post('/api/apps/status/token'))
    const directory = await body(await adminAPI.get('/api/v1/extensions/status/principals?kind=user', { headers: { Authorization: 'Bearer ' + token.token } }))
    return directory.items.find(item => item.label === username).principal
  }
  const originalPrincipal = await directPrincipal()
  const component = (await proxy(adminAPI, 'PUT', '/v1/manage/components', { label: 'Direct identity grant fixture', enabled: true, public_enabled: false, public_label: '', revision: 0, grants: [{ principal: originalPrincipal, permission: 'read' }], monitors: [] })).item
  const originalAccount = await login(username)
  const originalList = await proxy(originalAccount, 'GET', '/v1/components')
  expect(originalList.items.some(item => item.id === component.id)).toBe(true)
  expect((await proxy(originalAccount, 'GET', '/v1/components/' + component.id)).item.label).toBe('Direct identity grant fixture')
  const originalToken = await body(await originalAccount.post('/api/apps/status/token'))
  await body(await adminAPI.delete('/api/admin/users/' + username))
  await body(await adminAPI.post('/api/admin/users', { data: { username, password, role: 'user', primary_group: groupA } }))
  expect(await directPrincipal()).not.toBe(originalPrincipal)
  const reused = await adminAPI.post('/api/v1/extensions/status/request', { headers: { Authorization: 'Bearer ' + originalToken.token }, data: { method: 'GET', path: '/v1/components' } })
  expect(reused.status()).toBe(403)
  const recreated = await login(username)
  const visible = await proxy(recreated, 'GET', '/v1/components')
  expect(visible.items.some(item => item.id === component.id)).toBe(false)
  const freshToken = await body(await recreated.post('/api/apps/status/token'))
  const detail = await recreated.post('/api/v1/extensions/status/request', { headers: { Authorization: 'Bearer ' + freshToken.token }, data: { method: 'GET', path: '/v1/components/' + component.id } })
  expect(detail.status()).toBe(404)
  expect(await detail.text()).not.toContain('Direct identity grant fixture')
})


test('closing the browser does not cancel a probe or stop the background scheduler', async ({ browser }) => {
  const address = Object.values(networkInterfaces()).flat().find(item => item.family === 'IPv4' && !item.internal && /^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/.test(item.address))?.address
  const held = [], requests = []
  const receiver = http.createServer((request, response) => {
    requests.push(request.url)
    if (requests.length === 1) held.push(response)
    else { response.writeHead(204); response.end() }
  })
  await new Promise((resolve, reject) => { receiver.once('error', reject); receiver.listen(0, '0.0.0.0', resolve) })
  const port = receiver.address().port
  const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US' })
  try {
    const component = (await proxy(adminAPI, 'PUT', '/v1/manage/components', {
      label: 'Process-owned scheduler fixture', enabled: true, public_enabled: false, public_label: '', revision: 0, grants: [],
      monitors: [{ label: 'Local read-only fixture', kind: 'http', enabled: true, interval_seconds: 60, timeout_seconds: 15, config: { version: 1, url: 'http://' + address + ':' + port + '/health', plain_http: true, networks: [address + '/32'], expected_status: 204 } }]
    })).item
    const page = await context.newPage()
    await openStatus(page)
    await expect(page.frameLocator('iframe').getByRole('heading', { name: 'Process-owned scheduler fixture', exact: true })).toBeVisible()
    const operation = await proxy(adminAPI, 'GET', '/v1/manage/operations')
    await proxy(adminAPI, 'POST', '/v1/manage/resume', { queue_fingerprint: operation.queue_fingerprint, probes: true, outbox: false })
    await expect.poll(() => held.length, { timeout: 10000 }).toBe(1)
    await context.close()
    expect(service.exitCode).toBeNull()
    held[0].writeHead(204); held[0].end()
    const snapshot = async () => (await proxy(adminAPI, 'GET', '/v1/components/' + component.id)).item.monitors[0]
    await expect.poll(async () => (await snapshot()).outcome, { timeout: 10000 }).toBe('success')
    expect((await snapshot()).observed_at).not.toBe('')
    const configured = (await proxy(adminAPI, 'GET', '/v1/manage/components')).items.find(item => item.id === component.id).monitors[0]
    await proxy(adminAPI, 'POST', '/v1/manage/probes/request', { id: configured.id, revision: configured.revision })
    await expect.poll(() => requests.length, { timeout: 10000 }).toBe(2)
    await expect.poll(async () => (await snapshot()).state, { timeout: 10000 }).toBe('operational')
    const final = await proxy(adminAPI, 'GET', '/v1/manage/operations')
    expect(final.settings.outbox_paused).toBe(true)
    expect(requests).toEqual(['/health', '/health'])
  } finally {
    await context.close()
    await proxy(adminAPI, 'PUT', '/v1/manage/settings', { public_enabled: false, probes_paused: true, outbox_paused: true, portal_url: '', portal_networks: [] })
    held.forEach(response => response.destroy())
    receiver.closeAllConnections()
    await new Promise(resolve => receiver.close(resolve))
  }
})

test('Status outage leaves Portal authentication, reading and queue available and recovers after restart', async ({ browser }) => {
  const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US' })
  const restartStatus = async () => {
    service = launch(statusBinary, ['serve', '-listen', '0.0.0.0:' + new URL(statusBase).port, '-database', join(folder, 'status.db'), '-storage-key-file', join(folder, 'storage.key'), '-pairing-file', join(folder, 'pairing.json')])
    await ready(statusBase + '/readyz', service)
  }
  try {
    const page = await context.newPage()
    await openStatus(page)
    const frame = page.frameLocator('iframe')
    await expect(frame.getByRole('heading', { name: 'Private operations A', exact: true })).toBeVisible()
    service.kill('SIGTERM')
    await expect.poll(() => service.exitCode, { timeout: 10000 }).not.toBeNull()
    await frame.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect(frame.getByRole('alert')).toBeVisible()
    await expect(frame.getByRole('heading', { name: 'Private operations A', exact: true })).toHaveCount(0)
    for (const path of ['/healthz', '/api/me', '/api/home', '/api/admin/batch/queue']) {
      const response = await adminAPI.get(path)
      expect(response.status(), 'Portal remains available: ' + path).toBe(200)
    }
    await restartStatus()
    await frame.getByRole('button', { name: 'Refresh', exact: true }).click()
    await expect(frame.getByRole('heading', { name: 'Private operations A', exact: true })).toBeVisible()
  } finally {
    if (service.exitCode !== null) await restartStatus()
    await context.close()
  }
})

test('Portal outage does not stop scheduled Status observations or approved public reads', async () => {
  const address = Object.values(networkInterfaces()).flat().find(item => item.family === 'IPv4' && !item.internal && /^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/.test(item.address))?.address
  const held = [], requests = []
  const receiver = http.createServer((request, response) => {
    requests.push(request.url)
    if (requests.length === 1) held.push(response)
    else { response.writeHead(204); response.end() }
  })
  await new Promise((resolve, reject) => { receiver.once('error', reject); receiver.listen(0, '0.0.0.0', resolve) })
  const restartPortal = async () => {
    portal = launch(portalBinary, [], { RP_CONFIG: join(folder, 'portal.yaml') })
    await ready(base + '/healthz', portal)
  }
  try {
    const component = (await proxy(adminAPI, 'PUT', '/v1/manage/components', {
      label: 'Private Portal outage fixture', enabled: true, public_enabled: true, public_label: 'Approved independence fixture', revision: 0, grants: [],
      monitors: [{ label: 'Independent local read', kind: 'http', enabled: true, interval_seconds: 30, timeout_seconds: 15, config: { version: 1, url: 'http://' + address + ':' + receiver.address().port + '/health', plain_http: true, networks: [address + '/32'], expected_status: 204 } }]
    })).item
    await proxy(adminAPI, 'PUT', '/v1/manage/settings', { public_enabled: true, probes_paused: true, outbox_paused: true, portal_url: '', portal_networks: [] })
    const operation = await proxy(adminAPI, 'GET', '/v1/manage/operations')
    await proxy(adminAPI, 'POST', '/v1/manage/resume', { queue_fingerprint: operation.queue_fingerprint, probes: true, outbox: false })
    await expect.poll(() => held.length, { timeout: 10000 }).toBe(1)
    portal.kill('SIGTERM')
    await expect.poll(() => portal.exitCode, { timeout: 10000 }).not.toBeNull()
    held[0].writeHead(204); held[0].end()
    const publicSnapshot = async () => {
      const response = await fetch(statusBase + '/public/v1/status')
      expect(response.status).toBe(200)
      const body = await response.json()
      expect(JSON.stringify(body)).not.toContain('Private Portal outage fixture')
      return body.items.find(item => item.id === component.id)
    }
    await expect.poll(async () => (await publicSnapshot()).observed_at, { timeout: 10000 }).not.toBe('')
    // A second interval runs with Portal still stopped, without a browser or API trigger.
    await expect.poll(async () => (await publicSnapshot()).state, { timeout: 40000, intervals: [250, 500, 1000] }).toBe('operational')
    expect(requests.length).toBeGreaterThanOrEqual(2)
    expect(portal.exitCode).not.toBeNull()
    expect(service.exitCode).toBeNull()
    expect((await fetch(statusBase + '/readyz')).status).toBe(200)
  } finally {
    if (portal.exitCode !== null) await restartPortal()
    await proxy(adminAPI, 'PUT', '/v1/manage/settings', { public_enabled: false, probes_paused: true, outbox_paused: true, portal_url: '', portal_networks: [] })
    held.forEach(response => response.destroy())
    receiver.closeAllConnections()
    await new Promise(resolve => receiver.close(resolve))
  }
})

test('backend disable, reinstall and uninstall revoke access without changing Portal or the standalone service', async ({ browser }) => {
  const endpoint = '/api/admin/apps/status/backend'
  const original = await body(await adminAPI.get(endpoint))
  const token = await body(await adminAPI.post('/api/apps/status/token'))
  const save = (current, enabled) => adminAPI.put(endpoint, { data: { revision: current.revision, label: current.label, base_url: current.base_url, audience: current.audience, enabled, key_id: '', signing_key: '', policy: current.policy } })
  const disabled = await body(await save(original, false))
  const denied = await adminAPI.post('/api/v1/extensions/status/request', { headers: { Authorization: 'Bearer ' + token.token }, data: { method: 'GET', path: '/v1/components' } })
  expect(denied.status()).toBe(403)
  await body(await save(disabled, true))
  expect((await proxy(adminAPI, 'GET', '/v1/components')).items.some(item => item.id === componentA.id)).toBe(true)
  const bundle = readFileSync(resolve(__dirname, '../../../dist/status', JSON.parse(readFileSync(resolve(__dirname, '../app.json'), 'utf8')).version, 'status.zip'))
  await body(await adminAPI.post('/api/admin/apps/install', { multipart: { bundle: { name: 'status.zip', mimeType: 'application/zip', buffer: bundle } } }))
  const reinstalled = await body(await adminAPI.get(endpoint))
  expect(reinstalled.enabled).toBe(false)
  expect(reinstalled.has_key).toBe(false)
  expect(reinstalled.instance_id).not.toBe(original.instance_id)
  const stale = await adminAPI.post('/api/v1/extensions/status/request', { headers: { Authorization: 'Bearer ' + token.token }, data: { method: 'GET', path: '/v1/components' } })
  expect(stale.status()).toBe(403)
  await body(await adminAPI.delete('/api/admin/apps/status'))
  expect((await adminAPI.get(endpoint)).status()).toBe(404)
  expect((await adminAPI.get('/app-assets/status/index.html')).status()).toBe(404)
  const installed = await body(await adminAPI.get('/api/apps'))
  expect(installed.apps.some(item => item.id === 'status')).toBe(false)
  // A fresh installation is safely usable only after a deliberate backend pairing.
  await body(await adminAPI.post('/api/admin/apps/install', { multipart: { bundle: { name: 'status.zip', mimeType: 'application/zip', buffer: bundle } } }))
  expect((await adminAPI.get(endpoint)).status()).toBe(404)
  const context = await browser.newContext({ storageState: await adminAPI.storageState(), locale: 'en-US' })
  try {
    const page = await context.newPage()
    await openStatus(page)
    const frame = page.frameLocator('iframe')
    await expect(frame.getByRole('alert')).toBeVisible()
    await expect(frame.getByText('Backend compatibility could not be verified. Status data is not displayed until the connection and service capabilities are verified.', { exact: true })).toBeVisible()
    await expect(frame.getByRole('heading', { name: 'Private operations A', exact: true })).toHaveCount(0)
    await expect(frame.getByRole('button', { name: 'Manage', exact: true })).toHaveCount(0)
  } finally {
    await context.close()
    await body(await adminAPI.delete('/api/admin/apps/status'))
  }
  for (const path of ['/healthz', '/api/me', '/api/home', '/api/admin/batch/queue']) expect((await adminAPI.get(path)).status(), 'Portal unchanged after app uninstall: ' + path).toBe(200)
  expect((await fetch(statusBase + '/readyz')).status).toBe(200)
  expect(service.exitCode).toBeNull()
})
