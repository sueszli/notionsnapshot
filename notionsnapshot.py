# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Save a public Notion page, and every page it links to, as self-contained HTML files."""

import argparse
import base64
import functools
import re
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Error, Page, TimeoutError, sync_playwright

# runs inside the loaded page: strips notion's app, inlines every asset, rewrites links to local files
SNAPSHOT_JS = r"""
async (rootId) => {
  const pageId = (s) => s.match(/[0-9a-f]{32}/)?.[0]
  const loaded = new Set(performance.getEntriesByType('resource').map((e) => e.name))
  const dataUrl = async (u) => (await window.dataUrl(u)) ?? u
  // stylesheets reference every font notion has, so only embed what this page actually used
  const inlineUrls = async (css, base, all) => {
    let out = '', i = 0
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
    const href = abs(link, 'href').href, css = await dataUrl(href)
    if (!css.startsWith('data:')) { link.setAttribute('href', href); continue }
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
    const u = abs(a, 'href'), id = pageId(u.pathname)
    if (u.host !== location.host || !id) a.setAttribute('href', u.href)
    else if (id === pageId(location.pathname) && u.hash) a.setAttribute('href', u.hash)
    else { a.setAttribute('href', id === rootId ? 'index.html' : `${id}.html`); links.push(u.origin + u.pathname) }
  }
  return ['<!doctype html>\n' + doc.documentElement.outerHTML, links]
}
"""


def page_id(url: str) -> str | None:
    m = re.search(r"[0-9a-f]{32}", url.split("?")[0])
    return m and m.group()


def settle(page: Page) -> None:
    # notion keeps streaming blocks in after the spinners are gone, so also wait until the block count stops changing
    page.wait_for_function("document.querySelector('.notion-frame') && !document.querySelector('.loading-spinner, .notion-unknown-block')", timeout=60_000)
    count = -1
    while count != (count := page.locator("[data-block-id]").count()):
        # notion only renders blocks near the viewport, so grow it until the whole page fits
        height = page.evaluate("document.querySelector('.notion-frame .notion-scroller')?.scrollHeight ?? 0")
        page.set_viewport_size({"width": 1280, "height": max(1000, height)})
        page.wait_for_timeout(1000)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="public page, e.g. https://example.notion.site/Page-0123456789abcdef0123456789abcdef")
    parser.add_argument("out", nargs="?", default="snapshot", help="output directory (default: snapshot)")
    args = parser.parse_args()
    if not (root := page_id(args.url)):
        parser.error(f"no page id in {args.url}")

    subprocess.run([sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"], check=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    todo, seen = [args.url], {root}

    with sync_playwright() as p:
        # a persistent profile keeps notion's ~300 scripts in the http cache, without it repeated runs get rate limited
        browser = p.chromium.launch_persistent_context(Path.home() / ".cache" / "notionsnapshot", viewport={"width": 1280, "height": 1000})
        page = browser.pages[0]
        # notion's bot check rejects the headless user agent
        user_agent = page.evaluate("navigator.userAgent").replace("Headless", "")
        browser.new_cdp_session(page).send("Network.setUserAgentOverride", {"userAgent": user_agent})
        page.add_init_script("performance.setResourceTimingBufferSize(100000)")

        # fetched from python because in-page fetch is blocked by cors for images on other domains
        @functools.cache
        def data_url(url: str) -> str | None:
            try:
                res = page.request.get(url, headers={"user-agent": user_agent})
            except Error:
                return None
            mime = res.headers.get("content-type", "application/octet-stream").split(";")[0]
            return f"data:{mime};base64,{base64.b64encode(res.body()).decode()}" if res.ok else None

        page.expose_function("dataUrl", data_url)

        while todo:
            url = todo.pop()
            try:
                page.goto(url, timeout=60_000)
                settle(page)
                # expand toggles, including ones nested inside other toggles. marking each one stops a toggle that won't open from looping forever
                toggles = page.locator(".notion-list-item-box-left [role=button][aria-expanded=false]:not([data-clicked])")
                while toggles.count():
                    button = toggles.first.element_handle()
                    button.evaluate("(b) => b.setAttribute('data-clicked', '')")
                    button.click()
                    settle(page)
            except TimeoutError:
                print(f"skipped {url}, it did not load. if many pages fail notion is rate limiting you, wait a few minutes and run again")
                continue

            html, links = page.evaluate(SNAPSHOT_JS, root)
            path = out / ("index.html" if page_id(url) == root else f"{page_id(url)}.html")
            path.write_text(html, encoding="utf-8")
            print(f"{path}  {len(html) // 1024} KiB  {url}")

            for link in links:
                if (pid := page_id(link)) and pid not in seen:
                    seen.add(pid)
                    todo.append(link)
        browser.close()


if __name__ == "__main__":
    main()
