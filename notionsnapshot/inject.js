// injected into every page before notion's own scripts

// notion loads more resources than the default buffer of 250 holds, and the snapshot reads them to pick which fonts to embed
performance.setResourceTimingBufferSize(100000)

const pageId = (s) => s.match(/[0-9a-f]{32}/)?.[0]

window.notionsnapshot = {
  // strips notion's app, inlines every asset and rewrites links to local files. returns [html, links to other pages]
  snapshot: async ({ rootId, css }) => {
    const loaded = new Set(performance.getEntriesByType('resource').map((e) => e.name))
    const dataUrl = async (u) => (await window.dataUrl(u)) ?? u
    // stylesheets reference every font notion has, so only embed what this page actually used
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

    // work on a detached copy, notion's app keeps mutating the live page while we await
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

    // notion fades embeds in with javascript, which the snapshot doesn't have
    for (const e of doc.querySelectorAll('iframe')) e.parentElement.style.opacity = 1
    for (const e of doc.querySelectorAll('.collectionSearch')) e.parentElement.style.display = 'none'

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
