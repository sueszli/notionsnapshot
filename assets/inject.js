// single-file --browser-script

addEventListener('DOMContentLoaded', () => dispatchEvent(new CustomEvent('single-file-user-script-init')))

addEventListener('single-file-on-before-capture-request', async (event) => {
  event.preventDefault()
  const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms))
  // wait until no new blocks appear
  const settle = async () => {
    for (let n = -1; n !== (n = document.querySelectorAll('[data-block-id]').length); ) await sleep(1000)
  }
  await settle()
  // expand toggles, nested ones too
  for (let button; (button = document.querySelector('.notion-list-item-box-left [role=button][aria-expanded=false]:not([data-clicked])')); ) {
    button.setAttribute('data-clicked', '')
    button.click()
    await settle()
  }
  // one url per page for --crawl-replace-URLs
  for (const a of document.querySelectorAll(`a[href^="/"], a[href^="${location.origin}/"]`)) {
    const url = new URL(a.href)
    a.setAttribute('href', url.origin + url.pathname.replace(/^\/p\//, '/'))
  }
  dispatchEvent(new CustomEvent('single-file-on-before-capture-response'))
})
