// injected before notion's scripts. all notion-markup-specific code lives here

// default buffer of 250 is too small, snapshot() reads it to pick fonts
performance.setResourceTimingBufferSize(100000)

const pageId = (s) => s.match(/[0-9a-f]{32}/)?.[0]

window.notionsnapshot = {
  isLoaded: () => !!document.querySelector('.notion-frame') && !document.querySelector('.loading-spinner, .notion-unknown-block'),

  blockCount: () => document.querySelectorAll('[data-block-id]').length,

  pageHeight: () => document.querySelector('.notion-frame .notion-scroller')?.scrollHeight ?? 0,

  // mark clicked toggles, so a stuck one isn't clicked forever
  nextToggle: () => {
    const button = document.querySelector('.notion-list-item-box-left [role=button][aria-expanded=false]:not([data-clicked])')
    button?.setAttribute('data-clicked', '')
    return button
  },

  // live dom => self-contained html. returns [html, subpage links]
  snapshot: async ({ rootId, css }) => {
    const loaded = new Set(performance.getEntriesByType('resource').map((e) => e.name))
    const dataUrl = async (u) => (await window.dataUrl(u)) ?? u
    // only embed fonts this page loaded
    const inlineUrls = async (text, base, all) => {
      let out = ''
      let i = 0
      for (const m of text.matchAll(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g)) {
        if (m[2].startsWith('data:')) continue
        const u = new URL(m[2], base).href
        out += text.slice(i, m.index) + `url("${all || loaded.has(u) ? await dataUrl(u) : u}")`
        i = m.index + m[0].length
      }
      return out + text.slice(i)
    }

    // detached copy: notion keeps mutating the live dom
    const doc = new DOMParser().parseFromString(document.documentElement.outerHTML, 'text/html')
    const abs = (e, attr) => new URL(e.getAttribute(attr), location.href)
    doc.querySelectorAll('script, noscript, base, link:not([rel=stylesheet]), meta:not([charset], [name=viewport]), .notion-overlay-container, .notion-collection-view-select, #intercom-frame, .intercom-lightweight-app').forEach((e) => e.remove())
    doc.querySelectorAll('iframe').forEach((e) => e.closest('.notion-page-content') || e.remove())

    for (const link of doc.querySelectorAll('link[rel=stylesheet]')) {
      const href = abs(link, 'href').href
      const sheet = await dataUrl(href)
      if (!sheet.startsWith('data:')) {
        link.setAttribute('href', href)
        continue
      }
      const style = doc.createElement('style')
      style.textContent = await inlineUrls(await (await fetch(sheet)).text(), href, false)
      link.replaceWith(style)
    }
    const style = doc.createElement('style')
    style.textContent = css
    doc.head.append(style)

    for (const e of doc.querySelectorAll('[style*="url("]')) e.setAttribute('style', await inlineUrls(e.getAttribute('style'), location.href, true))
    for (const e of doc.querySelectorAll('img[src], video[src], audio[src], source[src]')) {
      const src = abs(e, 'src').href
      if (!src.startsWith('data:')) e.setAttribute('src', await dataUrl(src))
      e.removeAttribute('srcset')
      e.removeAttribute('loading')
    }

    // notion fades embeds in via js
    for (const e of doc.querySelectorAll('iframe')) e.parentElement.style.opacity = 1
    for (const e of doc.querySelectorAll('.collectionSearch')) e.parentElement.style.display = 'none'

    // toc links => #<block id without dashes>
    for (const e of doc.querySelectorAll('[data-block-id]')) e.id = e.dataset.blockId.replaceAll('-', '')
    const links = []
    for (const a of doc.querySelectorAll('a[href]')) {
      const u = abs(a, 'href')
      const id = pageId(u.pathname)
      if (u.host !== location.host || !id) {
        a.setAttribute('href', u.href)
      } else if (id === pageId(location.pathname) && u.hash) {
        a.setAttribute('href', u.hash)
      } else {
        a.setAttribute('href', id === rootId ? 'index.html' : `${id}.html`)
        links.push(u.origin + u.pathname)
      }
    }
    return ['<!doctype html>\n' + doc.documentElement.outerHTML, links]
  },
}
