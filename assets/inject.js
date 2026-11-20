// single-file --browser-script: expand the notion page, then let single-file capture it

addEventListener('DOMContentLoaded', () => dispatchEvent(new CustomEvent('single-file-user-script-init')))

addEventListener('single-file-on-before-capture-request', async (event) => {
  event.preventDefault()
  const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms))
  // blocks stream in after load
  const settle = async () => {
    for (let n = -1; n !== (n = document.querySelectorAll('[data-block-id]').length); ) await sleep(1000)
  }
  await settle()
  // nested toggles appear after their parent opens. data-clicked stops a stuck one from looping
  for (let button; (button = document.querySelector('.notion-list-item-box-left [role=button][aria-expanded=false]:not([data-clicked])')); ) {
    button.setAttribute('data-clicked', '')
    button.click()
    await settle()
  }
  // drop /p/ and ?pvs= so --crawl-replace-URLs finds the saved file
  for (const a of document.querySelectorAll(`a[href^="/"], a[href^="${location.origin}/"]`)) {
    const url = new URL(a.href)
    a.setAttribute('href', url.origin + url.pathname.replace(/^\/p\//, '/'))
  }
  dispatchEvent(new CustomEvent('single-file-on-before-capture-response'))
})
