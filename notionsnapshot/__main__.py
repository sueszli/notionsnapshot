# /// script
# requires-python = ">=3.11"
# dependencies = ["appdirs", "beautifulsoup4", "cssutils", "html5lib", "playwright", "requests"]
#
# [tool.uv]
# exclude-newer = "2026-11-01T00:00:00Z"
# ///
import urllib.parse
import urllib.request
import os
import shutil
import base64
import functools
import logging
import re
import uuid
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Set

from playwright.sync_api import Page
from bs4 import BeautifulSoup, Tag
import html5lib  # implicitly used by bs4
import requests
import cssutils

from argparser import ARGS
from driver import DriverInitializer

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
cssutils.log.setLevel(logging.CRITICAL)
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

    @functools.cache
    @staticmethod
    def fetch(url: str) -> Optional[Tuple[str, bytes]]:
        try:
            session = requests.Session()
            session.trust_env = False
            response = session.get(url, timeout=ARGS.timeout)
            response.raise_for_status()
            return response.headers.get("content-type", "application/octet-stream").split(";")[0], response.content
        except Exception as error:
            LOG.critical(f"error downloading asset on '{url}' - the online link to it will be used instead \n\t{error}")
            return None

    @staticmethod
    def download_asset(url: str) -> str:
        # assets are embedded as data urls, so every page is a single self-contained file
        asset = FileManager.fetch(url)
        if asset is None:
            return url
        mime, content = asset
        return f"data:{mime};base64,{base64.b64encode(content).decode()}"

    @staticmethod
    def save_page(soup: BeautifulSoup, url: str) -> None:
        # don't prettify html, it breaks the page
        html_str = str(soup)
        filename = FileManager.get_filename_from_url(url)
        output_path = Path(FileManager.output_dir + "/" + filename)
        with open(output_path, "wb") as f:
            f.write(html_str.encode("utf-8").strip())
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
            soup = BeautifulSoup(Scraper.page.content(), "html5lib")
            Scraper._clean_up(soup)
            Scraper._download_images(soup)
            Scraper._download_stylesheets(soup)
            Scraper._insert_injection_hooks(soup)
            Scraper._link_to_table_view_subpages(soup)
            subpage_urls = Scraper._link_anchors(soup)
            FileManager.save_page(soup, url)

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

    @staticmethod
    def _clean_up(soup: BeautifulSoup) -> None:
        for script in soup.findAll("script"):
            script.decompose()
        for aif_production in soup.findAll("iframe", {"src": "https://aif.notion.so/aif-production.html"}):
            aif_production.decompose()
        for intercom_frame in soup.findAll("iframe", {"id": "intercom-frame"}):
            intercom_frame.decompose()
        for intercom_div in soup.findAll("div", {"class": "intercom-lightweight-app"}):
            intercom_div.decompose()
        for overlay_div in soup.findAll("div", {"class": "notion-overlay-container"}):
            overlay_div.decompose()
        # preloads, icons and manifests point at files the self-contained page doesn't have
        for link in soup.findAll("link"):
            if "stylesheet" not in link.get("rel", []):
                link.decompose()
        for vendors_css in soup.find_all("link", href=lambda text: bool(text) and "vendors~" in text):
            vendors_css.decompose()
        for collection_selector in soup.findAll("div", {"class": "notion-collection-view-select"}):
            collection_selector.decompose()
        for tag in ["description", "twitter:card", "twitter:site", "twitter:title", "twitter:description", "twitter:image", "twitter:url", "apple-itunes-app"]:
            unwanted_tag = soup.find("meta", attrs={"name": tag})
            if unwanted_tag and isinstance(unwanted_tag, Tag):
                unwanted_tag.decompose()
        for tag in ["og:site_name", "og:type", "og:url", "og:title", "og:description", "og:image"]:
            unwanted_og_tag = soup.find("meta", attrs={"property": tag})
            if unwanted_og_tag and isinstance(unwanted_og_tag, Tag):
                unwanted_og_tag.decompose()

    @staticmethod
    def _download_images(soup: BeautifulSoup) -> None:
        images = [img for img in soup.findAll("img") if img.has_attr("src") and not (img.has_attr("class") and "notion-emoji" in img["class"])]
        LOG.info(f"found {len(images)} images to download")
        for img in images:
            is_notion_asset = img["src"].startswith("/")
            if "data:image" not in img["src"]:
                img_src = img["src"]
                if is_notion_asset:
                    img_src = f'https://www.notion.so{img["src"]}'
                img["src"] = FileManager.download_asset(img_src)
            elif is_notion_asset:
                img["src"] = f'https://www.notion.so{img["src"]}'

        emojis = [img for img in soup.findAll("img") if img.has_attr("class") and "notion-emoji" in img["class"]]
        LOG.info(f"found {len(emojis)} emojis to download")
        for img in emojis:
            style = cssutils.parseStyle(img["style"])
            spritesheet = style["background"]
            spritesheet_url = spritesheet[spritesheet.find("(") + 1 : spritesheet.find(")")]
            download_path = FileManager.download_asset(f"https://www.notion.so{spritesheet_url}")
            style["background"] = spritesheet.replace(spritesheet_url, download_path)
            img["style"] = style.cssText

        is_in_both = lambda img: img in images and img in emojis
        shared = [is_in_both(img) for img in images + emojis]
        assert not any(shared), "img is both an image and an emoji"

    @staticmethod
    def _download_stylesheets(soup: BeautifulSoup) -> None:
        def is_stylesheet(link):
            return link.has_attr("href") and link["href"].startswith("/") and "vendors~" not in link["href"]

        stylesheets = [link for link in soup.findAll("link", rel="stylesheet") if is_stylesheet(link)]
        base_url = "https://www.notion.so"

        # stylesheets reference every font notion has, so only embed the ones this page loaded
        loaded_paths = {urllib.parse.urlparse(url).path for url in Scraper.page.evaluate("performance.getEntriesByType('resource').map((e) => e.name)")}
        url_pattern = re.compile(r"url\((https?:\/\/www\.notion\.so)?(\/[^)]+)\)")

        def url_replacer(match):
            full_url, partial_url = match.groups()
            if not full_url:
                font_url = f"{base_url}{partial_url}"
                return f"url({FileManager.download_asset(font_url) if partial_url in loaded_paths else font_url})"
            return match.group(0)

        for link in stylesheets:
            css_url = f'{base_url}{link["href"]}'
            asset = FileManager.fetch(css_url)
            if asset is None:
                link["href"] = css_url
                continue
            style = soup.new_tag("style")
            style.string = url_pattern.sub(url_replacer, asset[1].decode("utf-8"))
            link.replace_with(style)

    @staticmethod
    def _insert_injection_hooks(soup: BeautifulSoup) -> None:
        # add ids and classes for 'injection.js' to work
        toggle_blocks = soup.findAll("div", {"class": "notion-toggle-block"})
        for query in ["header", "sub_header", "sub_sub_header"]:
            header_toggle_blocks = soup.findAll("div", {"class": f"notion-selectable notion-{query}-block"})
            [toggle_blocks.append(block) for block in header_toggle_blocks if block.select_one("div[role=button]") is not None]
        for toggle_block in toggle_blocks:
            toggle_button = toggle_block.select_one("div[role=button]")
            toggle_content = toggle_block.find("div", {"class": None, "style": ""})
            if toggle_button and toggle_content:
                toggle_button["class"] = toggle_block.get("class", []) + ["notionsnapshot-toggle-button"]
                toggle_content["class"] = toggle_content.get("class", []) + ["notionsnapshot-toggle-content"]
                toggle_content.attrs["notionsnapshot-toggle-id"] = toggle_button.attrs["notionsnapshot-toggle-id"] = uuid.uuid4()

        injection_dir = Path(__file__).parent / "injections"
        style = soup.new_tag("style")
        style.string = (injection_dir / "injection.css").read_text(encoding="utf-8")
        assert soup.head is not None
        soup.head.insert(-1, style)
        script = soup.new_tag("script")
        script.string = (injection_dir / "injection.js").read_text(encoding="utf-8")
        assert soup.body is not None
        soup.body.insert(-1, script)

    @staticmethod
    def _link_to_table_view_subpages(soup: BeautifulSoup) -> None:
        # this function broke with a recent notion update
        tables = soup.findAll("div", {"class": "notion-table-view"})
        LOG.info(f"found {len(tables)} tables")
        for table in tables:
            rows = table.findAll("div", {"class": "notion-collection-item"})
            LOG.info(f"found {len(rows)} rows with links to subpages in table")
            for row in rows:
                subpage_path = "/" + row["data-block-id"].replace("-", "")
                row_name_span = row.find("span")
                # row_name_span["style"] = row_name_span["style"].replace("pointer-events: none;", "")
                subpage_anchor = soup.new_tag(
                    "a",
                    attrs={"href": subpage_path, "style": "cursor: pointer; color: inherit; text-decoration: none; fill: inherit;"},
                )
                row_name_span.wrap(subpage_anchor)

    @staticmethod
    def _link_anchors(soup: BeautifulSoup) -> List[str]:
        subpage_urls = []

        domain = f'{ARGS.url.split("notion.site")[0]}notion.site'
        anchors = soup.find_all("a", href=True)

        for a in anchors:
            url = a["href"]

            is_relative_url = url.startswith("/")
            if is_relative_url:
                url = f'{domain}/{a["href"].split("/")[-1]}'

            is_external_url = not url.startswith(domain)
            if is_external_url:
                continue

            scroller_parent = a.find_parent("div", class_="notion-scroller")
            is_scroller = scroller_parent is not None and len(scroller_parent) > 0
            topbar_parent = a.find_parent("div", class_="notion-topbar")
            is_topbar = topbar_parent is not None and len(topbar_parent) > 0
            is_table_of_contents = "#" in url

            if is_table_of_contents:
                # add ids and classes for 'injection.js' to work
                arr = url.split("#")
                url = arr[0]
                a["href"] = f"#{arr[-1]}"
                a["class"] = a.get("class", []) + ["notionsnapshot-anchor-link"]

            elif (is_scroller or is_topbar) and FileManager.get_page_id(url):
                filename = FileManager.get_filename_from_url(url)
                a["href"] = filename
                subpage_urls.append(url)

            else:
                # remove all other links
                del a["href"]
                a.name = "span"
                children = [child for child in ([a] + a.find_all()) if child.has_attr("style")]
                for child in children:
                    style = cssutils.parseStyle(child["style"])
                    style["cursor"] = "default"
                    child["style"] = style.cssText

        return subpage_urls


if __name__ == "__main__":
    FileManager.setup()
    Scraper().run()
