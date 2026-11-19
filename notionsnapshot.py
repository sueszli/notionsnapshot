# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.65", "tyro"]
#
# [tool.uv]
# exclude-newer = "2026-11-19T00:00:00Z"
# ///
import base64
import functools
import re
import subprocess
import sys
from pathlib import Path

import tyro
from playwright.sync_api import Error, Page, TimeoutError, sync_playwright


def page_id(url: str) -> str | None:
    m = re.search(r"[0-9a-f]{32}", url.split("?")[0])
    return m and m.group()


def settle(page: Page) -> None:
    page.wait_for_function("notionsnapshot.isLoaded()", timeout=60_000)
    # blocks keep streaming in after the spinners are gone: wait for a stable count
    count = -1
    while count != (count := page.evaluate("notionsnapshot.blockCount()")):
        # notion only renders blocks near the viewport
        page.set_viewport_size({"width": 1280, "height": max(1000, page.evaluate("notionsnapshot.pageHeight()"))})
        page.wait_for_timeout(1000)


def main(url: str, out: Path = Path("snapshot"), /) -> None:
    root = page_id(url)
    assert root, f"url must contain a 32 character notion page id: {url}"
    subprocess.run([sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"], check=True)
    out.mkdir(parents=True, exist_ok=True)
    todo, seen = [url], {root}

    with sync_playwright() as p:
        # persistent http cache, else notion rate limits repeated runs
        browser = p.chromium.launch_persistent_context(Path.home() / ".cache" / "notionsnapshot", viewport={"width": 1280, "height": 1000})
        page = browser.pages[0]
        # bot check rejects "HeadlessChrome"
        user_agent = page.evaluate("navigator.userAgent").replace("Headless", "")
        browser.new_cdp_session(page).send("Network.setUserAgentOverride", {"userAgent": user_agent})
        page.add_init_script(path=Path(__file__).parent / "assets" / "inject.js")
        css = (Path(__file__).parent / "assets" / "inject.css").read_text(encoding="utf-8")

        # in-page fetch is cors-blocked for cross-origin assets
        @functools.cache
        def data_url(url: str) -> str | None:
            try:
                res = page.request.get(url, headers={"user-agent": user_agent})
            except Error:
                res = None
            if not (res and res.ok):
                print(f"could not embed {url}, the snapshot links to it online")
                return None
            mime = res.headers.get("content-type", "application/octet-stream").split(";")[0]
            return f"data:{mime};base64,{base64.b64encode(res.body()).decode()}"

        page.expose_function("dataUrl", data_url)

        while todo:
            url = todo.pop()
            try:
                page.goto(url, timeout=60_000)
                settle(page)
                # toggles nest: re-query after each click
                while button := page.evaluate_handle("notionsnapshot.nextToggle()").as_element():
                    button.click()
                    settle(page)
            except TimeoutError:
                print(f"skipped {url}, it did not load. if many pages fail notion is rate limiting you, wait a few minutes and run again")
                continue

            html, links = page.evaluate("notionsnapshot.snapshot", {"rootId": root, "css": css})
            path = out / ("index.html" if page_id(url) == root else f"{page_id(url)}.html")
            path.write_text(html, encoding="utf-8")
            print(f"{path}  {len(html) // 1024} KiB  {url}")

            for link in links:
                if (pid := page_id(link)) and pid not in seen:
                    seen.add(pid)
                    todo.append(link)
        browser.close()


if __name__ == "__main__":
    tyro.cli(main, prog="notionsnapshot")
