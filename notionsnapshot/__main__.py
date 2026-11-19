# /// script
# requires-python = ">=3.11"
# dependencies = ["appdirs", "beautifulsoup4", "cssutils", "html5lib", "playwright", "requests", "rich"]
#
# [tool.uv]
# exclude-newer = "2026-11-01T00:00:00Z"
# ///
import urllib.parse
import urllib.request
import os
import shutil
import glob
import hashlib
import mimetypes
import re
import uuid
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Set

from playwright.sync_api import ElementHandle, Page
from bs4 import BeautifulSoup, Tag
import html5lib  # implicitly used by bs4
import requests
import cssutils
from appdirs import user_cache_dir

from argparser import ARGS
from driver import DriverInitializer
from logger import LOG_SINGLETON as LOG, trace


class FileManager:
    output_dir: str = ""
    assets_dir: str = ""
    cache_dir: str = ""
    css_injection_file: str = ""
    js_injection_file: str = ""

    @staticmethod
    def setup() -> None:
        page_name = FileManager.get_page_name()
        FileManager.output_dir = os.path.join("snapshots", page_name)
        FileManager.assets_dir = os.path.join(FileManager.output_dir, "assets")

        cache_base_dir = user_cache_dir(appname="notion-snapshot", appauthor="sueszli")
        FileManager.cache_dir = os.path.join(cache_base_dir, page_name)

        FileManager._init_output_dir()

        css_file, js_file = FileManager._copy_injections_to_assets_dir()
        FileManager.css_injection_file = css_file
        FileManager.js_injection_file = js_file

    @staticmethod
    def get_page_name() -> str:
        page_id = urllib.parse.urlparse(ARGS.url).path[1:]
        return page_id[: page_id.rfind("-")].lower()

    @trace()
    @staticmethod
    def _init_output_dir() -> None:
        if not ARGS.disable_caching and os.path.exists(FileManager.assets_dir):
            shutil.copytree(FileManager.assets_dir, FileManager.cache_dir, dirs_exist_ok=True)
            LOG.info("cached assets from previous snapshot for this url")

        if os.path.exists(FileManager.output_dir):
            shutil.rmtree(FileManager.output_dir)
            LOG.info(f"removed previous snapshot for this url")

        os.makedirs(FileManager.output_dir, exist_ok=True)
        os.makedirs(FileManager.assets_dir, exist_ok=True)
        if not ARGS.disable_caching:
            os.makedirs(FileManager.cache_dir, exist_ok=True)

    @staticmethod
    def _copy_injections_to_assets_dir() -> Tuple[str, str]:
        injection_dir = Path(__file__).parent / "injections"
        css_out = Path(FileManager.assets_dir) / "injection.css"
        js_out = Path(FileManager.assets_dir) / "injection.js"
        shutil.copy(injection_dir / "injection.js", js_out)
        shutil.copy(injection_dir / "injection.css", css_out)
        relative_css_out = str(css_out.relative_to(FileManager.output_dir)).replace("\\", "/")
        relative_js_out = str(js_out.relative_to(FileManager.output_dir)).replace("\\", "/")
        return relative_css_out, relative_js_out

    @trace()
    @staticmethod
    def download_asset(url: str, filename: str = "") -> str:
        if not filename:
            filename = FileManager._generate_filename(url)

        already_downloaded = glob.glob(os.path.join(FileManager.assets_dir, filename + ".*"))
        if already_downloaded:
            LOG.info(f"asset '{filename}' was already downloaded")
            return str(Path(already_downloaded[0]).relative_to(FileManager.output_dir)).replace("\\", "/")

        if not ARGS.disable_caching and (cached := FileManager._load_from_cache(filename)) is not None:
            LOG.info(f"asset '{filename}' was found in cache")
            return cached

        destination = Path(FileManager.assets_dir) / filename
        try:
            session = requests.Session()
            session.trust_env = False
            response = session.get(url)
            response.raise_for_status()

            missing_file_extension = not bool(destination.suffix)
            if missing_file_extension:
                suffix = Path(urllib.parse.urlparse(url).path).suffix
                question_mark = "%3f"
                if suffix:
                    if question_mark in suffix.lower():
                        suffix = re.split(question_mark, suffix, flags=re.IGNORECASE)[0]
                    destination = destination.with_suffix(suffix)
                else:
                    content_type = response.headers.get("content-type")
                    assert content_type is not None
                    mimetype = mimetypes.guess_extension(content_type)
                    assert mimetype is not None
                    destination = destination.with_suffix(mimetype)

            with open(destination, "wb") as f:
                f.write(response.content)

            return str(destination.relative_to(FileManager.output_dir)).replace("\\", "/")

        except Exception as error:
            LOG.critical(f"error downloading asset on '{url}' - the online link to it will be used instead \n\t{error}")
            return url

    @staticmethod
    def _generate_filename(url: str) -> str:
        parsed_url = urllib.parse.urlparse(url)
        queryless_url = parsed_url.netloc + parsed_url.path
        params = urllib.parse.parse_qs(parsed_url.query)
        # having width in hash as name allows fetching different image resolutions
        if "width" in params.keys():
            queryless_url = queryless_url + f"?width={params['width']}"
        filename = hashlib.sha1(str.encode(queryless_url)).hexdigest()
        return filename

    @staticmethod
    def _load_from_cache(filename: str) -> Optional[str]:
        filename = filename if Path(filename).suffix else filename + ".*"
        cache_path = os.path.join(FileManager.cache_dir, filename)
        cached = glob.glob(cache_path)
        if cached:
            shutil.copy(cached[0], FileManager.assets_dir)
            return os.path.join("assets", os.path.basename(cached[0]))
        return None

    @staticmethod
    def save_page(soup: BeautifulSoup, url: str) -> None:
        # don't prettify html, it breaks the page
        html_str = str(soup)
        filename = FileManager.get_filename_from_url(url)
        output_path = Path(FileManager.output_dir + "/" + filename)
        with open(output_path, "wb") as f:
            f.write(html_str.encode("utf-8").strip())
        LOG.info(f"saved page\n\n\n\n\n\n\n")

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

    @trace()
    @staticmethod
    def _load_page(url: str) -> None:
        prev_page = ""

        def is_page_loaded() -> bool:
            nonlocal prev_page
            d = Scraper.page
            root_block = d.query_selector_all(".notion-presence-container")
            if root_block:
                unknown_blocks = d.query_selector_all(".notion-unknown-block")
                loading_spinners = d.query_selector_all(".loading-spinner")
                scrollers = d.query_selector_all(".notion-scroller")
                scrollers_with_children = [scroller for scroller in scrollers if scroller.query_selector_all("div")]
                page_changed = prev_page != d.content()
                all_scrollers_loaded = len(scrollers_with_children) == len(scrollers)
                if all_scrollers_loaded and not unknown_blocks and not loading_spinners and not page_changed:
                    return True
                LOG.info(f"waiting for: {len(unknown_blocks)} unknown blocks - {len(loading_spinners)} loading spinners - {len(scrollers_with_children)}/{len(scrollers)} scrollers with children")
            prev_page = d.content()
            return False

        Scraper.page.goto(url)
        if not Scraper._wait_until(is_page_loaded):
            LOG.info("timed out waiting for page to load, proceeding anyways (might be because of infinite spinners)")
            time.sleep(10)
        LOG.info("page loaded")

        mode = "dark" if ARGS.dark_mode else "light"
        Scraper.page.evaluate("__console.environment.ThemeStore.setState({ mode: '" + mode + "' })")
        LOG.info(f"set theme to {mode}-mode")

    @trace(print_args=False)
    @staticmethod
    def _expand_toggle_blocks(expanded_count: int = 0) -> None:
        # playwright returns a new handle for every query, so expanded blocks are marked in the dom instead of kept in a list
        expanded_marker = "data-notionsnapshot-expanded"

        def get_toggle_blocks() -> List[ElementHandle]:
            toggle_blocks = Scraper.page.query_selector_all(f".notion-toggle-block:not([{expanded_marker}])")
            header_toggle_blocks = []
            queries = [f".notion-selectable.notion-{type}-block:not([{expanded_marker}])" for type in ["header", "sub_header", "sub_sub_header"]]
            for query in queries:
                blocks = Scraper.page.query_selector_all(query)
                for block in blocks:
                    if block.query_selector_all("div[role=button]"):
                        header_toggle_blocks.append(block)
            toggle_blocks += header_toggle_blocks
            return toggle_blocks

        def is_block_expanded(b: ElementHandle) -> bool:
            content = b.query_selector("div:not([style])")
            unknown_children = b.query_selector_all(".notion-unknown-block")
            is_loading = b.query_selector_all(".loading-spinner")
            return bool(content) and not unknown_children and not is_loading

        for block in get_toggle_blocks():
            block.evaluate(f"(b) => b.setAttribute('{expanded_marker}', '')")
            toggle_block_button = block.query_selector("div[role=button]")
            assert toggle_block_button is not None
            svg = toggle_block_button.query_selector("svg")
            block_style = svg.get_attribute("style") if svg else None
            assert block_style is not None, "toggle block style should be string"
            is_expanded = "(0deg)" in block_style
            if not is_expanded:
                toggle_block_button.evaluate("(b) => b.click()")
                if not Scraper._wait_until(lambda: is_block_expanded(block)):
                    LOG.critical("timeout while expanding block - manually check if it's expanded in the snapshot")
                    continue
            expanded_count += 1

        nested_toggle_blocks = get_toggle_blocks()
        LOG.info(f"expanded {expanded_count} toggle blocks so far - found {len(nested_toggle_blocks)} nested blocks expand next")
        if nested_toggle_blocks:
            Scraper._expand_toggle_blocks(expanded_count)

    @staticmethod
    def _clean_up(soup: BeautifulSoup) -> None:
        for script in soup.findAll("script"):
            script.decompose()
        for aif_production in soup.findAll("iframe", {"src": "https://aif.notion.so/aif-production.soup"}):
            aif_production.decompose()
        for intercom_frame in soup.findAll("iframe", {"id": "intercom-frame"}):
            intercom_frame.decompose()
        for intercom_div in soup.findAll("div", {"class": "intercom-lightweight-app"}):
            intercom_div.decompose()
        for overlay_div in soup.findAll("div", {"class": "notion-overlay-container"}):
            overlay_div.decompose()
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

    @trace()
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

    @trace()
    @staticmethod
    def _download_stylesheets(soup: BeautifulSoup) -> None:
        def is_stylesheet(link):
            return link.has_attr("href") and link["href"].startswith("/") and "vendors~" not in link["href"]

        stylesheets = [link for link in soup.findAll("link", rel="stylesheet") if is_stylesheet(link)]
        base_url = "https://www.notion.so"

        for link in stylesheets:
            download_path = FileManager.download_asset(f'{base_url}{link["href"]}')

            css_file_path = os.path.join(FileManager.output_dir, download_path)
            # Open file with UTF-8 encoding
            with open(css_file_path, "r", encoding="utf-8") as f:
                css_content = f.read()

            # Write back with UTF-8 encoding
            with open(css_file_path, "w", encoding="utf-8") as f:
                url_pattern = re.compile(r"url\((https?:\/\/www\.notion\.so)?(\/[^)]+)\)")

                def url_replacer(match):
                    full_url, partial_url = match.groups()
                    if not full_url:
                        font_file_name = os.path.basename(partial_url)
                        font_download_url = f"{base_url}{partial_url}"
                        font_local_path = FileManager.download_asset(font_download_url, font_file_name)
                        return f"url({font_local_path})"
                    return match.group(0)

                # Replace the URLs in the CSS content
                modified_css_content = url_pattern.sub(url_replacer, css_content)
                f.write(modified_css_content)

            link["href"] = download_path

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

        assert soup.head is not None
        soup.head.insert(-1, soup.new_tag("link", rel="stylesheet", href=FileManager.css_injection_file))
        assert soup.body is not None
        soup.body.insert(-1, soup.new_tag("script", type="text/javascript", src=FileManager.js_injection_file))

    @trace()
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

    @trace()
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
