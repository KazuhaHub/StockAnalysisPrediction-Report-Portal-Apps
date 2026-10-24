const { test, expect, request } = require('@playwright/test')
const { spawn, spawnSync } = require('node:child_process')
const { mkdtempSync, writeFileSync, readFileSync, rmSync } = require('node:fs')
const { tmpdir, networkInterfaces } = require('node:os')
const { join, resolve } = require('node:path')
const { randomBytes } = require('node:crypto')
const net = require('node:net')
const portalBinary = process.env.PORTAL_BINARY
const statusBinary = process.env.STATUS_BINARY
let folder, portal, service, base, statusBase, adminAPI, groupA, groupB, componentA, componentB
const processes = [], contexts = []
const password = 'Fixture-Only-Password-1022'
function freePort() { return new Promise((resolve, reject) => { const server = net.createServer(); server.once('error', reject); server.listen(0, '0.0.0.0', () => { const port = server.address().port; server.close(() => resolve(port)) }) }) }
function launch(binary, args, env) { const process = spawn(binary, args, { cwd: folder, env: { ...global.process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] }); let output = ''; process.stdout.on('data', chunk => { output += chunk }); process.stderr.on('data', chunk => { output += chunk }); process.output = () => output; processes.push(process); return process }
async function ready(url, process) { const deadline = Date.now() + 30000; while (Date.now() < deadline) { if (process.exitCode !== null) throw new Error('Fixture process exited: ' + process.output()); try { const response = await fetch(url); if (response.ok) return } catch {} await new Promise(r => setTimeout(r, 100)) } throw new Error('Fixture readiness timed out') }
async function body(response) { const text = await response.text(); if (!response.ok()) throw new Error('Fixture request failed (' + response.status() + '): ' + text); return JSON.parse(text) }
async function login(username) { const context = await request.newContext({ baseURL: base }); contexts.push(context); await body(await context.post('/api/login', { data: { username, password } })); return context }
async function proxy(api, method, path, input) { const token = await body(await api.post('/api/apps/status/token')); return body(await api.post('/api/v1/extensions/status/request', { headers: { Authorization: 'Bearer ' + token.token }, data: { method, path, ...(input === undefined ? {} : { body: input }) } })) }

test.beforeAll(async () => {
  test.skip(!portalBinary || !statusBinary, 'PORTAL_BINARY and STATUS_BINARY are required for real integration acceptance')
  folder = mkdtempSync(join(tmpdir(), 'status-acceptance-'))
  const address = Object.values(networkInterfaces()).flat().find(i => i.family === 'IPv4' && !i.internal && /^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/.test(i.address))?.address
  if (!address) throw new Error('A private interface is required; loopback exceptions are deliberately not enabled')
  const port = await freePort(), servicePort = await freePort()
  base = 'http://127.0.0.1:' + port; statusBase = 'http://127.0.0.1:' + servicePort
  const config = join(folder, 'portal.yaml')
  writeFileSync(config, 'listen: "127.0.0.1:' + port + '"\nsecret_key: "' + randomBytes(32).toString('hex') + '"\ndb_driver: "sqlite"\ndb_path: "' + join(folder, 'portal.db') + '"\n', { mode: 0o600 })
  const seeded = spawnSync(portalBinary, ['adduser', 'admin', password, 'admin'], { cwd: folder, env: { ...process.env, RP_CONFIG: config }, encoding: 'utf8' })
  if (seeded.status !== 0) throw new Error('Portal fixture account setup failed: ' + seeded.stderr)
  portal = launch(portalBinary, [], { RP_CONFIG: config }); await ready(base + '/healthz', portal)
  adminAPI = await login('admin')
  const bundle = readFileSync(resolve(__dirname, '../../../dist/status/0.1.0-dev/status.zip'))
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

test('real Portal bridge shows each current OU only its permitted component', async ({ browser }) => {
  for (const [username, visible, hidden] of [['viewer-a', 'Private operations A', 'Private operations B'], ['viewer-b', 'Private operations B', 'Private operations A']]) {
    const api = await login(username), context = await browser.newContext({ storageState: await api.storageState(), locale: 'en-US' }), page = await context.newPage()
    await page.goto(base + '/apps/x/status')
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
  await page.goto(base + '/apps/x/status')
  const frame = page.frameLocator('iframe')
  await frame.getByRole('button', { name: 'Manage', exact: true }).click()
  await frame.getByRole('button', { name: 'New component', exact: true }).click()
  await frame.getByLabel('Internal label', { exact: true }).fill('UI configured service')
  await frame.getByLabel('Enabled', { exact: true }).check()
  await frame.getByRole('button', { name: 'Add monitor', exact: true }).click()
  let monitors = frame.locator('fieldset')
  await monitors.nth(0).getByLabel('Internal label', { exact: true }).fill('First readiness')
  await monitors.nth(0).getByLabel('Target URL', { exact: true }).fill('https://first.invalid/health')
  await monitors.nth(0).getByLabel('Expected HTTP status (optional)', { exact: true }).fill('204')
  await frame.getByRole('button', { name: 'Add monitor', exact: true }).click()
  await monitors.nth(1).getByLabel('Internal label', { exact: true }).fill('Second readiness')
  await monitors.nth(1).getByLabel('Target URL', { exact: true }).fill('https://second.invalid/health')
  await frame.getByRole('button', { name: 'Load users and organizational units', exact: true }).click()
  await expect(frame.getByLabel('Internal label', { exact: true }).first()).toHaveValue('UI configured service')
  await expect(frame.locator('fieldset')).toHaveCount(2)
  await frame.locator('fieldset').nth(1).getByLabel('Target URL', { exact: true }).fill('invalid-target')
  await frame.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(frame.locator('[role="alert"]')).toBeVisible()
  await expect(frame.getByLabel('Internal label', { exact: true }).first()).toHaveValue('UI configured service')
  await expect(frame.locator('fieldset')).toHaveCount(2)
  await expect(frame.locator('fieldset').nth(1).getByLabel('Target URL', { exact: true })).toHaveValue('invalid-target')
  await frame.locator('fieldset').nth(1).getByLabel('Target URL', { exact: true }).fill('https://second.invalid/health')
  await frame.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(frame.getByRole('heading', { name: 'UI configured service', exact: true })).toBeVisible()
  expect(errors).toEqual([])
  const all = await proxy(adminAPI, 'GET', '/v1/manage/components')
  const saved = all.items.find(c => c.label === 'UI configured service')
  expect(saved.monitors.map(m => m.label)).toEqual(expect.arrayContaining(['First readiness', 'Second readiness']))
  expect(saved.monitors).toHaveLength(2)
  expect(saved.monitors.find(m => m.label === 'First readiness').config.expected_status).toBe(204)
  const editorCard = frame.locator('article').filter({ has: frame.getByRole('heading', { name: 'UI configured service', exact: true }) })
  await editorCard.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(frame.getByRole('button', { name: 'Request a check', exact: true })).toHaveCount(2)
  await frame.getByRole('button', { name: 'Request a check', exact: true }).first().click()
  await expect(frame.locator('[role="alert"]')).toBeVisible()
  const paused = await proxy(adminAPI, 'GET', '/v1/manage/operations')
  expect(paused.settings.probes_paused).toBe(true)
  await frame.getByRole('button', { name: 'Overview', exact: true }).click()
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
  await expect(page.getByRole('navigation', { name: 'Components', exact: true }).getByRole('button', { name: 'Next page', exact: true })).toBeDisabled()
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
  await context.addInitScript(() => { if (window.top === window) localStorage.setItem('rp_theme', 'dark') })
  const page = await context.newPage(), errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(base + '/apps/x/status')
  const frame = page.frameLocator('iframe')
  await expect(frame.getByRole('heading', { name: 'Service status', exact: true })).toBeVisible()
  await expect.poll(async () => page.frames().find(f => /\/app-assets\//.test(f.url()))?.evaluate(() => document.documentElement.style.colorScheme)).toBe('dark')
  await frame.getByRole('button', { name: 'Manage', exact: true }).click()
  await frame.getByRole('button', { name: 'Operations', exact: true }).click()
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
  await language.selectOption('zh-CN')
  await expect(frame.getByRole('heading', { name: '服务状态', exact: true })).toBeVisible()
  await frame.getByRole('combobox').first().selectOption('zh-TW')
  await expect(frame.getByRole('heading', { name: '服務狀態', exact: true })).toBeVisible()
  await frame.getByRole('combobox').first().selectOption('en-US')
  await frame.getByRole('button', { name: 'Overview', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(frame.getByRole('heading', { name: 'Private operations A', exact: true })).toBeVisible()
  expect(errors).toEqual([])
  await context.close()
})
