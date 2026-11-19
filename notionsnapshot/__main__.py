# /// script
# requires-python = ">=3.11"
# dependencies = ["appdirs", "playwright>=1.65"]
#
# [tool.uv]
# exclude-newer = "2026-11-19T00:00:00Z"
# ///
import urllib.parse
import os
import shutil
import base64
import functools
import logging
import re
import time
from pathlib import Path
from typing import Callable, Optional, Set

from playwright.sync_api import Error, Page

from argparser import ARGS
from driver import DriverInitializer

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
LOG = logging.getLogger("notionsnapshot")


class FileManager:
    output_dir: str = ""

    @staticmethod
    def setup() -> None:
        FileManager.output_dir = os.path.join("snapshots", FileManager.get_page_name())
        if os.path.exists(FileManager.output_dir):
            shutil.rmtree(FileManager.output_dir)
            LOG.info("removed previous snapshot for this url")
        os.makedirs(FileManager.output_dir)

    @staticmethod
    def get_page_name() -> str:
        page_id = urllib.parse.urlparse(ARGS.url).path[1:]
        return page_id[: page_id.rfind("-")].lower()

    @staticmethod
    def save_page(html: str, url: str) -> None:
        output_path = Path(FileManager.output_dir) / FileManager.get_filename_from_url(url)
        output_path.write_text(html, encoding="utf-8")
        LOG.info(f"saved {output_path}")

    @staticmethod
    def get_page_id(url: str) -> Optional[str]:
        # titles repeat and notion also links pages as /p/<title>-<id>, so the 32 character id is the only reliable name
        ids = re.findall(r"[0-9a-f]{32}", urllib.parse.urlparse(url).path)
        return ids[-1] if ids else None

    @staticmethod
    def get_filename_from_url(url: str) -> str:
        page_id = FileManager.get_page_id(url)
        return "index.html" if page_id == FileManager.get_page_id(ARGS.url) else f"{page_id}.html"


INJECT_CSS = (Path(__file__).parent / "inject.css").read_text(encoding="utf-8")


class Scraper:
    page: Page = DriverInitializer.get_page()

    will_visit: Set[str] = set([ARGS.url])
    visited: Set[str] = set()

    @staticmethod
    def run() -> None:
        while Scraper.will_visit:
            url = Scraper.will_visit.pop()

            Scraper._load_page(url)
            Scraper._expand_toggle_blocks()
            html, subpage_urls = Scraper.page.evaluate("notionsnapshot.snapshot", {"rootId": FileManager.get_page_id(ARGS.url), "css": INJECT_CSS})
            FileManager.save_page(html, url)

            Scraper.visited.add(url)
            Scraper.will_visit.update(page for page in subpage_urls if page not in Scraper.visited)
            LOG.info(f"pages left to scrape: {len(Scraper.will_visit)}")

        Scraper.page.context.close()

    @staticmethod
    def _wait_until(condition: Callable[[], bool]) -> bool:
        deadline = time.time() + ARGS.timeout
        while not condition():
            if time.time() > deadline:
                return False
            time.sleep(0.5)
        return True

    @staticmethod
    def _settle() -> None:
        is_loaded = lambda: bool(Scraper.page.query_selector(".notion-frame")) and not Scraper.page.query_selector(".loading-spinner, .notion-unknown-block")
        if not Scraper._wait_until(is_loaded):
            LOG.info("timed out waiting for page to load, proceeding anyways (might be because of infinite spinners)")

        # notion keeps streaming blocks in after the spinners are gone, so also wait until the block count stops changing
        count = -1
        while count != (count := len(Scraper.page.query_selector_all("[data-block-id]"))):
            # notion only renders blocks near the viewport, so grow it until the whole page fits
            height = Scraper.page.evaluate("document.querySelector('.notion-frame .notion-scroller')?.scrollHeight ?? 0")
            Scraper.page.set_viewport_size({"width": 900, "height": max(1200, height)})
            time.sleep(1)

    @staticmethod
    def _load_page(url: str) -> None:
        Scraper.page.goto(url)
        Scraper._settle()
        LOG.info("page loaded")

        mode = "dark" if ARGS.dark_mode else "light"
        Scraper.page.evaluate("__console.environment.ThemeStore.setState({ mode: '" + mode + "' })")
        LOG.info(f"set theme to {mode}-mode")

    @staticmethod
    def _expand_toggle_blocks() -> None:
        # expanding a toggle can reveal nested toggles, so look again after every click. marking each one stops a toggle that won't open from being clicked forever
        query = ".notion-list-item-box-left [role=button][aria-expanded=false]:not([data-notionsnapshot-clicked])"
        count = 0
        while button := Scraper.page.query_selector(query):
            button.evaluate("(b) => b.setAttribute('data-notionsnapshot-clicked', '')")
            button.click()
            Scraper._settle()
            count += 1
        LOG.info(f"expanded {count} toggle blocks")


# assets are embedded as data urls, so every page is a single self-contained file.
# fetched from python because in-page fetch is blocked by cors for images on other domains
@functools.cache
def data_url(url: str) -> Optional[str]:
    try:
        response = Scraper.page.request.get(url, timeout=ARGS.timeout * 1000)
    except Error as error:
        LOG.critical(f"error downloading asset on '{url}' - the online link to it will be used instead \n\t{error}")
        return None
    if not response.ok:
        LOG.critical(f"error downloading asset on '{url}' - the online link to it will be used instead \n\thttp {response.status}")
        return None
    mime = response.headers.get("content-type", "application/octet-stream").split(";")[0]
    return f"data:{mime};base64,{base64.b64encode(response.body()).decode()}"


if __name__ == "__main__":
    FileManager.setup()
    Scraper.page.expose_function("dataUrl", data_url)
    Scraper().run()
