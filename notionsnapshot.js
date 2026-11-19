// injected into every page before notion's own scripts. everything that depends on notion's markup lives here

performance.setResourceTimingBufferSize(100000)

const pageId = (s) => s.match(/[0-9a-f]{32}/)?.[0]

window.notionsnapshot = {
  isLoaded: () => !!document.querySelector('.notion-frame') && !document.querySelector('.loading-spinner, .notion-unknown-block'),

  blockCount: () => document.querySelectorAll('[data-block-id]').length,

  pageHeight: () => document.querySelector('.notion-frame .notion-scroller')?.scrollHeight ?? 0,

  // marking each toggle stops one that won't open from being clicked forever
  nextToggle: () => {
    const button = document.querySelector('.notion-list-item-box-left [role=button][aria-expanded=false]:not([data-clicked])')
    button?.setAttribute('data-clicked', '')
    return button
  },

  // strips notion's app, inlines every asset and rewrites links to local files. returns [html, links to other pages]
  snapshot: async (rootId) => {
    const loaded = new Set(performance.getEntriesByType('resource').map((e) => e.name))
    const dataUrl = async (u) => (await window.dataUrl(u)) ?? u
    // stylesheets reference every font notion has, so only embed what this page actually used
    const inlineUrls = async (css, base, all) => {
      let out = ''
      let i = 0
      for (const m of css.matchAll(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g)) {
        if (m[2].startsWith('data:')) continue
        const u = new URL(m[2], base).href
        out += css.slice(i, m.index) + `url("${all || loaded.has(u) ? await dataUrl(u) : u}")`
        i = m.index + m[0].length
      }
      return out + css.slice(i)
    }

    // work on a detached copy, notion's app keeps mutating the live page while we await
    const doc = new DOMParser().parseFromString(document.documentElement.outerHTML, 'text/html')
    const abs = (e, attr) => new URL(e.getAttribute(attr), location.href)
    doc.querySelectorAll('script, noscript, base, link:not([rel=stylesheet]), meta:not([charset], [name=viewport]), .notion-overlay-container').forEach((e) => e.remove())
    doc.querySelectorAll('iframe').forEach((e) => e.closest('.notion-page-content') || e.remove())
    for (const link of doc.querySelectorAll('link[rel=stylesheet]')) {
      const href = abs(link, 'href').href
      const css = await dataUrl(href)
      if (!css.startsWith('data:')) {
        link.setAttribute('href', href)
        continue
      }
      const style = doc.createElement('style')
      style.textContent = await inlineUrls(await (await fetch(css)).text(), href, false)
      link.replaceWith(style)
    }
    for (const e of doc.querySelectorAll('[style*="url("]')) e.setAttribute('style', await inlineUrls(e.getAttribute('style'), location.href, true))
    for (const e of doc.querySelectorAll('img[src], video[src], audio[src], source[src]')) {
      e.setAttribute('src', await dataUrl(abs(e, 'src').href))
      e.removeAttribute('srcset')
      e.removeAttribute('loading')
    }

    // table of contents links point at #<block id without dashes>
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
