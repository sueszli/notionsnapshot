// single-file --browser-script: runs in the page, single-file captures once the response event fires

addEventListener('DOMContentLoaded', () => dispatchEvent(new CustomEvent('single-file-user-script-init')))

addEventListener('single-file-on-before-capture-request', async (event) => {
  event.preventDefault()
  const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms))
  // blocks keep streaming in after load: wait for a stable count
  const settle = async () => {
    for (let count = -1; count !== (count = document.querySelectorAll('[data-block-id]').length); ) await sleep(1000)
  }
  await settle()
  // toggles nest: re-query after each click. mark clicked ones, so a stuck one isn't clicked forever
  for (let button; (button = document.querySelector('.notion-list-item-box-left [role=button][aria-expanded=false]:not([data-clicked])')); ) {
    button.setAttribute('data-clicked', '')
    button.click()
    await settle()
  }
  // one url per page (no /p/, no ?pvs=), so --crawl-replace-URLs can match links to saved files
  for (const a of document.querySelectorAll(`a[href^="/"], a[href^="${location.origin}/"]`)) {
    const url = new URL(a.href)
    a.setAttribute('href', url.origin + url.pathname.replace(/^\/p\//, '/'))
  }
  dispatchEvent(new CustomEvent('single-file-on-before-capture-response'))
})
