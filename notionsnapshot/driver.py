import os
import subprocess
import sys
from pathlib import Path

from appdirs import user_cache_dir
from playwright.sync_api import Page, sync_playwright

from argparser import ARGS


class DriverInitializer:
    @staticmethod
    def get_page() -> Page:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)

        # a persistent profile keeps notion's ~300 scripts in the http cache, without it repeated runs get rate limited
        profile_dir = os.path.join(user_cache_dir(appname="notion-snapshot", appauthor="sueszli"), "browser")
        context = sync_playwright().start().chromium.launch_persistent_context(profile_dir, headless=not ARGS.show_browser, viewport={"width": 900, "height": 1200})
        page = context.pages[0]

        # notion's bot check rejects the headless user agent
        user_agent = page.evaluate("navigator.userAgent").replace("Headless", "")
        context.new_cdp_session(page).send("Network.setUserAgentOverride", {"userAgent": user_agent})
        page.add_init_script(path=Path(__file__).parent / "inject.js")
        return page
