(function () {
  const root = document.getElementById('app'), { safeState, selectLocale } = StatusContracts
  let language = selectLocale(navigator.language), busy = false, componentOffset = 0, incidentOffset = 0
  const t = key => STATUS_LOCALES[language][key] || key
  function h(tag, text, className) { const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; return node }
  function pager(label, page, offset, jump) {
    const nav = h('nav'), previous = h('button', t('pagePrevious')), next = h('button', t('pageNext'))
    nav.setAttribute('aria-label', t(label))
    previous.type = next.type = 'button'
    previous.disabled = offset === 0; next.disabled = offset + 50 >= page.total
    previous.addEventListener('click', () => { jump(Math.max(0, offset - 50)); render() })
    next.addEventListener('click', () => { jump(offset + 50); render() })
    nav.append(previous, h('span', offset + ' / ' + page.total), next)
    return nav
  }
  async function render() {
    if (busy) return
    busy = true
    document.documentElement.lang = language
    root.replaceChildren()
    const header = h('header'), title = h('div'), languages = document.createElement('select')
    languages.setAttribute('aria-label', t('language'))
    for (const locale of Object.keys(STATUS_LOCALES)) { const option = h('option', STATUS_LOCALES[locale].languageName); option.value = locale; option.selected = locale === language; languages.append(option) }
    languages.addEventListener('change', () => { language = languages.value; render() })
    title.append(h('h1', t('title')), h('p', t('subtitle'))); header.append(title, languages); root.append(header)
    const content = h('section', '', 'grid'); root.append(content)
    try {
      const [status, incidents] = await Promise.all(['public/v1/status?limit=50&offset=' + componentOffset, 'public/v1/incidents?limit=50&offset=' + incidentOffset].map(path => fetch(path, { credentials: 'omit', cache: 'no-store' }).then(async response => { if (!response.ok) throw new Error(); return response.json() })))
      if (!status.items?.length) content.append(h('p', t('empty'), 'notice'))
      for (const component of status.items || []) {
        const card = h('article', '', 'card'), state = safeState(component.state), history = h('button', t('history')), chart = h('div')
        history.type = 'button'
        history.addEventListener('click', async () => {
          history.disabled = true
          try {
            const response = await fetch('public/v1/history?component_id=' + encodeURIComponent(component.id), { credentials: 'omit', cache: 'no-store' })
            if (!response.ok) throw new Error()
            const data = await response.json(), strip = h('div', '', 'history-strip')
            strip.setAttribute('aria-label', t('history'))
            for (const item of data.items || []) { const value = safeState(item.state), label = new Date(item.from).toLocaleString(language) + ' – ' + new Date(item.to).toLocaleString(language) + ': ' + t(value), bar = h('span', '', 'hour ' + value); bar.title = label; bar.setAttribute('role', 'img'); bar.setAttribute('aria-label', label); bar.tabIndex = 0; strip.append(bar) }
            chart.replaceChildren(h('p', t('wholeHours'), 'muted'), data.items?.length ? strip : h('p', t('noCoverage')))
          } catch { chart.replaceChildren(h('p', t('unavailable'), 'notice error')) } finally { history.disabled = false }
        })
        card.append(h('h2', component.label), h('span', t(state), 'badge ' + state), h('p', t('observed') + ': ' + (component.observed_at ? new Date(component.observed_at).toLocaleString(language) : '—'), 'muted'), history, chart); content.append(card)
      }
      root.append(pager('components', status, componentOffset, value => { componentOffset = value }))
      root.append(h('h2', t('incidents')))
      if (!incidents.items?.length) root.append(h('p', t('noIncidents'), 'muted'))
      for (const incident of incidents.items || []) { const card = h('article', '', 'card'); card.append(h('h3', incident.summary), h('p', new Date(incident.opened_at).toLocaleString(language))); root.append(card) }
      root.append(pager('incidents', incidents, incidentOffset, value => { incidentOffset = value }))
      root.append(h('small', t('pageUpdated') + ': ' + new Date(status.generated_at).toLocaleString(language)))
    } catch { content.replaceChildren(h('p', t('unavailable'), 'notice error')) } finally { busy = false }
  }
  if (matchMedia('(prefers-color-scheme: dark)').matches) { for (const [k,v] of Object.entries({'--bg':'#111827','--surface':'#182334','--text':'#eef3fa','--muted':'#b2bed0','--border':'#3d4b60'})) document.documentElement.style.setProperty(k,v) }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) render() })
  setInterval(() => { if (!document.hidden) render() }, 30000)
  render()
})()
