(function () {
  'use strict'
  const { proxyRequest, safeState, selectLocale, percentage, monitorHint, requestErrorKey } = StatusContracts
  let language = selectLocale(navigator.language), tab = 'overview', adminTab = 'components', admin = false, initialized = false
  let componentOffset = 0, componentSearch = '', exportedComponent = null
  let error = '', notice = '', generation = 0, sequence = 0, incidentOffset = 0, selectedComponent = '', selectedIncident = ''
  let editingComponent = null, editingCredential = null, directory = [], directoryOffset = 0, rendering = false, rerender = false, busy = false
  const pending = new Map(), root = document.getElementById('app')
  const t = key => STATUS_LOCALES[language][key] || key
  function h(tag, props, ...children) {
    const node = document.createElement(tag)
    for (const [key, value] of Object.entries(props || {})) {
      if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value)
      else if (key === 'class') node.className = value
      else if (key in node) node[key] = value
      else node.setAttribute(key, value)
    }
    // The Portal sandbox does not allow native form submission. Keep validation
    // and keyboard activation local without navigation or allow-forms access.
    if (tag === 'button' && props?.type === 'submit') {
      node.type = 'button'
      node.addEventListener('click', () => { const form = node.closest('form'); if (form?.reportValidity()) form.dispatchEvent(new Event('submit', { cancelable: true })) })
    }
    if (tag === 'form') node.addEventListener('keydown', event => {
      if (event.key === 'Enter' && event.target.tagName === 'INPUT' && event.target.type !== 'checkbox') {
        event.preventDefault()
        if (node.reportValidity()) node.dispatchEvent(new Event('submit', { cancelable: true }))
      }
    })
    children.flat().forEach(child => { if (child != null) node.append(child instanceof Node ? child : document.createTextNode(String(child))) })
    return node
  }
  function text(key, className = '') { return h('p', { class: className }, t(key)) }
  function button(key, action, primary = false) { return h('button', { type: 'button', class: primary ? 'primary' : '', onClick: action }, t(key)) }
  function field(key, input) { return h('label', {}, t(key), input) }
  function input(value = '', type = 'text') { return h('input', { value, type, autoComplete: type === 'password' ? 'new-password' : 'off' }) }
  function check(key, value = false) { const node = h('input', { type: 'checkbox', checked: value }); return { node, label: h('label', { class: 'check' }, node, t(key)) } }
  function select(options, value, multiple = false) {
    const node = h('select', { multiple, size: multiple ? Math.min(6, Math.max(2, options.length)) : 1 })
    options.forEach(([id, label]) => node.append(h('option', { value: id, selected: multiple ? value.includes(id) : id === value }, label)))
    return node
  }
  function errorText(e) { return e instanceof Error ? e.message : t('failed') }
  function showError(e) {
    error = errorText(e)
    root.querySelector('[data-app-error]')?.remove()
    const alert = h('div', { class: 'notice error', role: 'alert', tabIndex: -1, 'data-app-error': '' }, error)
    root.querySelector('header')?.after(alert)
    alert.focus()
  }
  function run(action, successKey = 'saved') { return async () => {
    if (busy) return
    busy = true
    root.setAttribute('aria-busy', 'true')
    const controls = [...root.querySelectorAll('button,input,select,textarea')].map(node => [node, node.disabled])
    controls.forEach(([node]) => { node.disabled = true })
    try { error = ''; await action(); notice = t(successKey); await render() }
    catch (e) { showError(e) }
    finally { controls.forEach(([node, disabled]) => { if (node.isConnected) node.disabled = disabled }); busy = false; root.removeAttribute('aria-busy') }
  } }

  function host(request) {
    if (window.parent === window) return Promise.reject(new Error(t('privateOnly')))
    return new Promise((resolve, reject) => {
      const reqId = 'status-' + (++sequence)
      const timer = setTimeout(() => { pending.delete(reqId); reject(new Error(t('unavailable'))) }, 25000)
      pending.set(reqId, { resolve, reject, timer })
      window.parent.postMessage({ type: 'rp:api', reqId, ...request }, '*')
    })
  }
  async function api(method, path, body) { return host(proxyRequest(method, path, body)) }
  function theme(snapshot) {
    if (!snapshot) return
    for (const [key, value] of Object.entries({ '--bg': snapshot.colorBgLayout, '--surface': snapshot.colorBg, '--text': snapshot.colorText, '--border': snapshot.colorBorder, '--primary': snapshot.colorPrimary })) if (typeof value === 'string') document.documentElement.style.setProperty(key, value)
    document.documentElement.style.colorScheme = snapshot.dark ? 'dark' : 'light'
    document.documentElement.style.setProperty('--muted', snapshot.dark ? '#b2bed0' : '#57657a')
  }
  window.addEventListener('message', event => {
    if (event.source !== window.parent || !event.data || typeof event.data !== 'object') return
    const data = event.data
    if (data.type === 'rp:init' || data.type === 'rp:theme') {
      theme(data.theme)
      if (!initialized) { initialized = true; start() }
      return
    }
    if (data.type !== 'rp:api:result') return
    const request = pending.get(data.reqId); if (!request) return
    clearTimeout(request.timer); pending.delete(data.reqId)
    if (data.ok) request.resolve(data.data)
    else request.reject(new Error(t(requestErrorKey(data.status))))
  })
  setInterval(() => { if (initialized && !document.hidden && !busy && !rendering && tab !== 'manage' && !exportedComponent && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA' && document.activeElement?.tagName !== 'SELECT') render() }, 30000)
  async function start() {
    try { const viewer = await api('GET', '/v1/me'); admin = viewer.admin === true; error = '' } catch (e) { error = errorText(e) }
    await render()
  }
  function badge(state) { state = safeState(state); return h('span', { class: 'badge ' + state }, t(state)) }
  function date(instant) { return instant ? new Date(instant).toLocaleString(language) : '—' }
  function table(headings, rows) { return h('div', { class: 'scroll' }, h('table', {}, h('thead', {}, h('tr', {}, headings.map(key => h('th', {}, t(key))))), h('tbody', {}, rows.map(row => h('tr', {}, row.map(cell => h('td', {}, cell))))))) }
  async function render() {
    if (rendering) { rerender = true; return }
    rendering = true
    try {
    const current = ++generation
    document.documentElement.lang = language
    root.replaceChildren()
    const locale = select(Object.keys(STATUS_LOCALES).map(id => [id, STATUS_LOCALES[id].languageName]), language)
    locale.setAttribute('aria-label', t('language')); locale.addEventListener('change', () => { language = locale.value; render() })
    root.append(h('header', {}, h('div', {}, h('h1', {}, t('title')), text('subtitle')), h('div', { class: 'row' }, locale, button('refresh', () => render()))))
    const tabs = ['overview', 'incidents', ...(admin ? ['manage'] : [])]
    root.append(h('nav', { 'aria-label': t('title') }, tabs.map(key => h('button', { class: tab === key ? 'active' : '', onClick: () => { tab = key; render() } }, t(key)))))
    if (error) root.append(h('div', { class: 'notice error', role: 'alert', tabIndex: -1, 'data-app-error': '' }, error))
    if (notice) root.append(h('div', { class: 'notice', role: 'status' }, notice))
    if (!initialized) { root.append(text(window.parent === window ? 'privateOnly' : 'loading')); return }
    const content = h('section', {}, text('loading')); root.append(content)
    try {
      if (tab === 'overview') await overview(content, current)
      else if (tab === 'incidents') await incidents(content, current)
      else await management(content, current)
    } catch (e) { if (current === generation) content.replaceChildren(h('div', { class: 'notice error', role: 'alert' }, errorText(e))) }    } finally {
      rendering = false
      if (rerender) { rerender = false; queueMicrotask(render) }
    }
  }
  async function overview(content, current) {
    const response = await api('GET', '/v1/components?limit=50&offset=' + componentOffset + '&q=' + encodeURIComponent(componentSearch)); if (current !== generation) return
    content.replaceChildren()
    const search = input(componentSearch), searchForm = h('form', {}, field('componentSearch', search), h('button', { type: 'submit' }, t('search')))
    searchForm.addEventListener('submit', event => { event.preventDefault(); componentSearch = search.value; componentOffset = 0; selectedComponent = ''; exportedComponent = null; render() }); content.append(searchForm)
    if (!response.items?.length) content.append(text('empty'))

    content.append(h('div', { class: 'grid' }, response.items.map(component => h('article', { class: 'card' }, h('h2', {}, component.label), badge(component.state), (component.monitors || []).map(monitor => h('div', { class: 'compact' }, h('h3', {}, monitor.label), badge(monitor.state), monitor.outcome === 'unsupported' ? text('unsupported', 'muted') : null, monitorHint(monitor) ? text(monitorHint(monitor), 'muted') : null, h('small', {}, t('observed') + ': ' + date(monitor.observed_at)), monitor.measurements?.balances ? balanceTable(monitor.measurements) : null)), button('history', () => { selectedComponent = component.id; render() })))))
    content.append(h('div', { class: 'toolbar' }, button('pagePrevious', () => { componentOffset = Math.max(0, componentOffset - 50); render() }), h('span', {}, componentOffset + ' / ' + response.total), button('pageNext', () => { if (componentOffset + 50 < response.total) { componentOffset += 50; render() } })))
    if (selectedComponent) {
      const detail = await api('GET', '/v1/components/' + encodeURIComponent(selectedComponent)); if (current !== generation) return
      content.append(h('section', { class: 'card' }, h('h2', {}, detail.item.label), text('componentDetail', 'muted'), table(['monitor', 'lastSuccess', 'nextCheck', 'latency'], (detail.item.monitors || []).map(m => [m.label, date(m.last_success_at), date(m.next_check_at), m.measurements?.latency_ms != null ? m.measurements.latency_ms + ' ms' : '—']))))
      const from = new Date(Date.now() - 7 * 86400000).toISOString(), to = new Date().toISOString()
      const query = '?component_id=' + encodeURIComponent(selectedComponent) + '&from=' + encodeURIComponent(from) + '&to=' + encodeURIComponent(to)
      const [history, hourly] = await Promise.all([api('GET', '/v1/history' + query), api('GET', '/v1/history/hourly' + query)]); if (current !== generation) return
      const rows = (history.items || []).map(item => [item.monitor_id.slice(0, 8), percentage(item.operational_ms, item.eligible_ms) || t('noCoverage'), Math.round(item.coverage_ms / 1000) + ' ' + t('seconds'), Math.round(item.unknown_ms / 1000) + ' ' + t('seconds'), Math.round(item.excluded_ms / 1000) + ' ' + t('seconds')])
      content.append(h('section', { class: 'card' }, h('h2', {}, t('history')), text('wholeHours', 'muted'), historyStrip(hourly.items || []), table(['monitor', 'history', 'coverage', 'unknownTime', 'excluded'], rows), button('exportJSON', run(async () => { const response = await api('GET', '/v1/components/export' + query); exportedComponent = response.item }, 'exportReady'))))
      if (exportedComponent?.component?.id === selectedComponent) content.append(field('exportJSON', h('textarea', { value: JSON.stringify(exportedComponent, null, 2), readOnly: true, rows: 12 })), text('exportCopyHint', 'muted'))
    }
  }
  function historyStrip(items) {
    return h('div', { class: 'history-strip', 'aria-label': t('history') }, items.map(item => { const state = safeState(item.state), label = date(item.from) + ' – ' + date(item.to) + ': ' + t(state); return h('span', { class: 'hour ' + state, title: label, 'aria-label': label, role: 'img', tabIndex: 0 }) }))
  }
  function balanceTable(metrics) { return h('section', {}, text('accountBalanceHint', 'muted'), table(['currency', 'total', 'cash', 'credit', 'granted', 'toppedUp'], metrics.balances.map(b => [b.currency, b.total ?? '—', b.cash ?? '—', b.credit ?? '—', b.granted ?? '—', b.topped_up ?? '—']))) }
  async function incidents(content, current) {
    const response = await api('GET', '/v1/incidents?limit=50&offset=' + incidentOffset); if (current !== generation) return
    content.replaceChildren()
    if (!response.items?.length) content.append(text('noIncidents'))
    response.items.forEach(item => content.append(h('article', { class: 'card' }, h('h2', {}, item.summary), badge(item.state), h('p', { class: 'muted' }, date(item.opened_at) + ' → ' + date(item.resolved_at)), button('history', () => { selectedIncident = item.id; render() }))))
    content.append(h('div', { class: 'toolbar' }, button('pagePrevious', () => { incidentOffset = Math.max(0, incidentOffset - 50); render() }), h('span', {}, incidentOffset + ' / ' + response.total), button('pageNext', () => { if (incidentOffset + 50 < response.total) { incidentOffset += 50; render() } })))
    if (selectedIncident) {
      const response = await api('GET', '/v1/incidents/' + encodeURIComponent(selectedIncident)); if (current !== generation) return
      const item = response.item
      content.append(h('section', { class: 'card' }, h('h2', {}, item.summary), (item.transitions || []).map(tr => h('p', {}, date(tr.occurred_at) + ' · ' + tr.message))))
      if (admin) {
        const summary = input(''), enabled = check('publishNarrative')
        const form = h('form', {}, field('publicSummary', summary), enabled.label, h('button', { type: 'submit', class: 'primary' }, t('publish')))
        form.addEventListener('submit', event => { event.preventDefault(); run(() => api('PUT', '/v1/manage/incidents/publication', { id: item.id, revision: item.revision, summary: summary.value, enabled: enabled.node.checked }))() }); content.append(form)
      }
    }
  }
  async function management(content, current) {
    content.replaceChildren(h('nav', {}, ['components', 'credentials', 'operations'].map(key => h('button', { class: adminTab === key ? 'active' : '', onClick: () => { adminTab = key; render() } }, t(key)))))
    if (adminTab === 'components') await manageComponents(content, current)
    else if (adminTab === 'credentials') await manageCredentials(content, current)
    else await operations(content, current)
  }
  async function loadDirectory() {
    const responses = await Promise.all(['ou', 'user'].map(kind => host({ method: 'GET', path: '/api/v1/extensions/status/principals?kind=' + kind + '&offset=' + directoryOffset })))
    directory.push(...responses.flatMap(response => response.items || [])); directory = [...new Map(directory.map(item => [item.principal, item])).values()]; directoryOffset += 100
  }
  async function manageComponents(content, current) {
    const [response, creds] = await Promise.all([api('GET', '/v1/manage/components'), api('GET', '/v1/manage/credentials')]); if (current !== generation) return
    content.append(button('newComponent', () => { editingComponent = {}; render() }, true))
    response.items.forEach(item => content.append(h('article', { class: 'card' }, h('h2', {}, item.label), h('small', {}, item.id + ' · ' + t('revision') + ' ' + item.revision), h('p', {}, item.enabled ? t('enabled') : t('paused')), button('edit', () => { editingComponent = item; render() }))))
    if (!editingComponent) return
    const value = editingComponent, name = input(value.label), publicLabel = input(value.public_label), enabled = check('enabled', !!value.enabled), published = check('publicComponent', !!value.public_enabled)
    const grants = value.grants || []
    const grantOptions = [...new Map([...directory.map(p => [p.principal, p.label + ' · ' + p.principal.slice(0, 12)]), ...grants.filter(g => !directory.some(p => p.principal === g.principal)).map(g => [g.principal, g.principal])]).entries()]
    const read = select(grantOptions, grants.filter(g => g.permission === 'read').map(g => g.principal), true), finance = select(grantOptions, grants.filter(g => g.permission === 'finance').map(g => g.principal), true)
    const monitorArea = h('div'), monitors = []
    const addMonitor = m => { const editor = monitorEditor(m, creds.items); monitors.push(editor); monitorArea.append(editor.element) }
    ;(value.monitors || []).forEach(addMonitor)
    const form = h('form', {}, h('h2', {}, value.id ? t('edit') : t('newComponent')), field('name', name), field('publicLabel', publicLabel), enabled.label, published.label, text('publicHint', 'muted'), button(directoryOffset ? 'directoryMore' : 'loadDirectory', () => { editingComponent = readForm(); run(loadDirectory)() }), field('readGrants', read), field('financeGrants', finance), text('grantHint', 'muted'), monitorArea, button('addMonitor', () => addMonitor({ kind: 'http', interval_seconds: 60, timeout_seconds: 5, enabled: true })), h('div', { class: 'row' }, h('button', { type: 'submit', class: 'primary' }, t('save')), button('cancel', () => { editingComponent = null; render() })))
    const readForm = () => {
      const grantValues = (node, permission) => [...node.selectedOptions].map(o => ({ principal: o.value, permission }))
      return { id: value.id, revision: value.revision || 0, label: name.value, public_label: publicLabel.value, enabled: enabled.node.checked, public_enabled: published.node.checked, grants: [...grantValues(read, 'read'), ...grantValues(finance, 'finance')], monitors: monitors.map(m => m.read()) }
    }
    form.addEventListener('submit', event => { event.preventDefault(); run(async () => { await api('PUT', '/v1/manage/components', readForm()); editingComponent = null })() }); content.append(form)
  }
  function monitorEditor(value, credentials) {
    const kind = select(['http', 'dify', 'postgres', 'deepseek', 'qwen', 'heartbeat'].map(id => [id, t(id)]), value.kind || 'http'), name = input(value.label), enabled = check('enabled', value.enabled !== false), interval = input(value.interval_seconds || 60, 'number'), timeout = input(value.timeout_seconds || 5, 'number')
    const credential = select([['', t('none')], ...credentials.map(c => [c.id, c.label + ' · ' + t(c.kind)])], value.credential_id || '')
    const config = value.config || {}, accountRef = input(config.account_ref), url = input(config.url), expectedStatus = input(config.expected_status || '', 'number'), bodyContains = input(config.body_contains), hostName = input(config.host), port = input(config.port || 5432, 'number'), database = input(config.database), networks = h('textarea', { value: (config.networks || []).join('\n'), rows: 2 }), plain = check('plainHTTP', !!config.plain_http), low = input(config.low_balance), recovery = input(config.recovery_balance), currency = select([['CNY', 'CNY'], ['USD', 'USD']], config.currency || 'CNY'), site = select([['china', t('china')], ['international', t('international')]], config.site || 'china')
    const target = h('div'), renderTarget = () => {
      target.replaceChildren()
      if (['http', 'dify'].includes(kind.value)) target.append(field('url', url), field('networks', networks), plain.label)
      if (kind.value === 'http') target.append(field('expectedStatus', expectedStatus), field('bodyContains', bodyContains), text('httpConditionHint', 'muted'))
      if (kind.value === 'postgres') target.append(field('host', hostName), field('port', port), field('database', database), field('networks', networks))
      if (['deepseek', 'qwen'].includes(kind.value)) target.append(text('accountBalanceHint', 'muted'), text('accountRefHint', 'muted'), field('accountRef', accountRef), field('low', low), field('recovery', recovery), field('currency', currency))
      if (kind.value === 'qwen') target.append(field('site', site))
    }
    kind.addEventListener('change', renderTarget); renderTarget()
    const element = h('fieldset', {}, h('legend', {}, t('monitor')), field('name', name), field('kind', kind), field('credential', credential), target, h('div', { class: 'row' }, field('interval', interval), field('timeout', timeout)), enabled.label)
    if (value.id) element.append(text('checkSavedHint', 'muted'), button('checkNow', run(() => api('POST', '/v1/manage/probes/request', { id: value.id, revision: value.revision }), 'checkQueued')))
    return { element, read() {
      const config = { version: 1 }
      if (['http', 'dify'].includes(kind.value)) { config.url = url.value; config.networks = networks.value.split(/\s+/).filter(Boolean); config.plain_http = plain.node.checked }
      if (kind.value === 'http') { config.expected_status = Number(expectedStatus.value); config.body_contains = bodyContains.value }
      if (kind.value === 'postgres') { config.host = hostName.value; config.port = Number(port.value); config.database = database.value; config.networks = networks.value.split(/\s+/).filter(Boolean) }
      if (['deepseek', 'qwen'].includes(kind.value)) { config.account_ref = accountRef.value; config.currency = currency.value; config.low_balance = low.value; config.recovery_balance = recovery.value }
      if (kind.value === 'qwen') config.site = site.value
      return { id: value.id, label: name.value, kind: kind.value, credential_id: credential.value, enabled: enabled.node.checked, interval_seconds: Number(interval.value), timeout_seconds: Number(timeout.value), config }
    } }
  }
  async function manageCredentials(content, current) {
    const response = await api('GET', '/v1/manage/credentials'); if (current !== generation) return
    content.append(text('secretHint', 'muted'), button('newCredential', () => { editingCredential = {}; render() }, true))
    response.items.forEach(item => content.append(h('article', { class: 'card' }, h('h2', {}, item.label), h('small', {}, t(item.kind) + ' · ' + item.id), button('edit', () => { editingCredential = item; render() }))))
    if (!editingCredential) return
    const value = editingCredential, name = input(value.label), kind = select(['http', 'dify', 'postgres', 'deepseek', 'qwen', 'heartbeat', 'notification'].map(id => [id, t(id)]), value.kind || 'deepseek'); kind.disabled = !!value.id
    const secrets = {}, area = h('div')
    for (const key of ['api_key', 'username', 'password', 'access_key_id', 'access_key_secret', 'security_token', 'token']) secrets[key] = input('', key === 'username' ? 'text' : 'password')
    const labels = { api_key: 'apiKey', username: 'username', password: 'password', access_key_id: 'accessID', access_key_secret: 'accessSecret', security_token: 'securityToken', token: 'notificationToken' }
    const keys = () => kind.value === 'postgres' ? ['username', 'password'] : kind.value === 'qwen' ? ['access_key_id', 'access_key_secret', 'security_token'] : kind.value === 'notification' ? ['token'] : ['api_key']
    const renderSecrets = () => area.replaceChildren(...keys().map(key => field(labels[key], secrets[key])))
    kind.addEventListener('change', renderSecrets); renderSecrets()
    const approval = check('deleteApproval')
    const form = h('form', {}, field('name', name), field('kind', kind), text('secretHint', 'muted'), area, h('button', { type: 'submit', class: 'primary' }, t('save')), button('cancel', () => { editingCredential = null; render() }))
    if (value.id) form.append(approval.label, button('delete', () => { if (approval.node.checked) run(async () => { await api('DELETE', '/v1/manage/credentials', { id: value.id, revision: value.revision }); editingCredential = null })() }))
    form.addEventListener('submit', event => { event.preventDefault(); run(async () => { const secret = Object.fromEntries(keys().filter(key => secrets[key].value).map(key => [key, secrets[key].value])); await api('PUT', '/v1/manage/credentials', { id: value.id, revision: value.revision || 0, label: name.value, kind: kind.value, ...(Object.keys(secret).length ? { secret } : {}) }); editingCredential = null })() }); content.append(form)
  }
  async function operations(content, current) {
    const [ops, components] = await Promise.all([api('GET', '/v1/manage/operations'), api('GET', '/v1/manage/components')]); if (current !== generation) return
    const credentials = await api('GET', '/v1/manage/credentials'); if (current !== generation) return
    const settings = ops.settings, rawRetention = input(settings.raw_retention_days, 'number'), historyRetention = input(settings.history_retention_days, 'number'), published = check('publicEnabled', settings.public_enabled), paused = check('probesPaused', settings.probes_paused), outboxPaused = check('outboxPaused', settings.outbox_paused), portal = input(settings.portal_url), networks = h('textarea', { value: (settings.portal_networks || []).join('\n'), rows: 2 })
    const settingsForm = h('form', {}, h('h2', {}, t('operations')), text('publicHint', 'muted'), published.label, paused.label, outboxPaused.label, field('portalURL', portal), field('portalNetworks', networks), text('retentionHint', 'muted'), field('rawRetention', rawRetention), field('historyRetention', historyRetention), h('button', { type: 'submit', class: 'primary' }, t('save')))
    settingsForm.addEventListener('submit', event => { event.preventDefault(); run(() => api('PUT', '/v1/manage/settings', { raw_retention_days: Number(rawRetention.value), history_retention_days: Number(historyRetention.value), public_enabled: published.node.checked, probes_paused: paused.node.checked, outbox_paused: outboxPaused.node.checked, portal_url: portal.value, portal_networks: networks.value.split(/\s+/).filter(Boolean) }))() }); content.append(settingsForm)
    const reviewed = check('reviewed')
    const queue = h('section', { class: 'card' }, h('h2', {}, t('outbox')), text('resumeHint', 'muted'), h('small', {}, t('queueFingerprint') + ': ' + ops.queue_fingerprint), reviewed.label, button('resume', () => { if (reviewed.node.checked) run(() => api('POST', '/v1/manage/resume', { queue_fingerprint: ops.queue_fingerprint, probes: true, outbox: true }))() }))
    queue.append(table(['component', 'state', 'attempts', 'reason', 'manage'], ops.outbox.map(n => [n.component_id.slice(0, 8), t(n.state === 'retry' ? 'retryState' : n.state), n.attempts, n.last_error, n.state === 'review_required' ? h('div', {}, button('discard', () => { if (reviewed.node.checked) run(() => api('POST', '/v1/manage/outbox/review', { id: n.id, queue_fingerprint: ops.queue_fingerprint, action: 'discard' }))() }), button('retry', () => { if (reviewed.node.checked) run(() => api('POST', '/v1/manage/outbox/review', { id: n.id, queue_fingerprint: ops.queue_fingerprint, action: 'retry_same_publisher' }))() })) : '—'])))
    content.append(queue)
    if (!components.items.length) return
    const componentOptions = components.items.map(c => [c.id, c.label]), component = select(componentOptions, componentOptions[0][0]), credentialOptions = credentials.items.filter(c => c.kind === 'notification').map(c => [c.id, c.label]), credential = select([['', t('none')], ...credentialOptions], ''), publisherEnabled = check('enabled'), publisherInfo = h('small')
    const pickPublisher = () => { const prior = ops.publishers.find(p => p.component_id === component.value); credential.value = prior?.credential_id || ''; publisherEnabled.node.checked = prior?.enabled || false; publisherInfo.textContent = 'notify:status-' + component.value }
    component.addEventListener('change', pickPublisher); pickPublisher()
    const publisherForm = h('form', {}, h('h2', {}, t('publishers')), text('publisherHint', 'muted'), field('component', component), publisherInfo, field('credential', credential), publisherEnabled.label, h('button', { type: 'submit', class: 'primary' }, t('save')))
    publisherForm.addEventListener('submit', event => { event.preventDefault(); run(() => { const prior = ops.publishers.find(p => p.component_id === component.value); return api('PUT', '/v1/manage/publishers', { component_id: component.value, publisher_name: 'status-' + component.value, credential_id: credential.value, enabled: publisherEnabled.node.checked, revision: prior?.revision || 0 }) })() }); content.append(publisherForm)
    const maintenanceComponent = select(componentOptions, componentOptions[0][0]), start = input(new Date().toISOString()), end = input(new Date(Date.now() + 3600000).toISOString()), summary = input('')
    const maintenanceForm = h('form', {}, h('h2', {}, t('scheduleMaintenance')), field('component', maintenanceComponent), field('maintenanceStart', start), field('maintenanceEnd', end), field('summary', summary), h('button', { type: 'submit', class: 'primary' }, t('scheduleMaintenance')))
    maintenanceForm.addEventListener('submit', event => { event.preventDefault(); run(() => api('POST', '/v1/manage/maintenance', { component_id: maintenanceComponent.value, starts_at: start.value, ends_at: end.value, summary: summary.value }))() }); content.append(maintenanceForm)
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && tab !== 'manage' && initialized) render() })
  setInterval(() => { if (!document.hidden && tab !== 'manage' && initialized && !pending.size) render() }, 30000)
  render()
  if (window.parent === window) { initialized = false; error = t('privateOnly'); render() }
})()
