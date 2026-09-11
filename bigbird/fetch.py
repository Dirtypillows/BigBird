"""Phase 1: hardcoded fetcher for fredmiranda.com's Buy & Sell Photo-Gear board.

fredmiranda.com sits behind Cloudflare. A plain httpx GET with full
browser-like headers still gets a 403 -- identical headers over curl succeed,
which points at Cloudflare fingerprinting the TLS/HTTP-2 handshake rather
than checking headers. Playwright drives a real Chromium, whose network
stack Cloudflare treats as a normal browser, so it's used here instead of
httpx per the brief's httpx-with-Playwright-fallback design.
"""

import time

from playwright.sync_api import sync_playwright

SITE = "fredmiranda"
BASE_URL = "https://www.fredmiranda.com"
BOARD_ID = 10

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def board_url(page: int) -> str:
    """Map a 1-based page number to the site's URL pattern.

    Page 1 is /forum/board/10/, page 2 is /forum/board/10/1/, page 3 is
    /forum/board/10/2/, etc -- the trailing path segment is (page - 1).
    """
    if page < 1:
        raise ValueError("page must be >= 1")
    if page == 1:
        return f"{BASE_URL}/forum/board/{BOARD_ID}/"
    return f"{BASE_URL}/forum/board/{BOARD_ID}/{page - 1}/"


def _fetch_one(browser, url: str, retries: int = 3, backoff_seconds: float = 5.0) -> str:
    """Fetch a single URL in its own fresh browser context.

    A fresh context per page (rather than reusing one context/page across
    the whole crawl) keeps each request looking like an independent visit,
    which noticeably reduces 403s from Cloudflare's session risk scoring.
    """
    last_status = None
    for attempt in range(1, retries + 1):
        context = browser.new_context(user_agent=USER_AGENT)
        try:
            page_obj = context.new_page()
            response = page_obj.goto(url, wait_until="domcontentloaded")
            if response is not None and response.status < 400:
                return page_obj.content()
            last_status = response.status if response else "no response"
        finally:
            context.close()
        if attempt < retries:
            time.sleep(backoff_seconds * attempt)
    raise RuntimeError(f"failed to fetch {url} after {retries} attempts: {last_status}")


def fetch_pages(pages: int, delay_seconds: float = 1.5):
    """Yield (page_number, html) for pages 1..pages, fetched one at a time."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for page in range(1, pages + 1):
                url = board_url(page)
                html = _fetch_one(browser, url)
                yield page, html
                if page < pages:
                    time.sleep(delay_seconds)
        finally:
            browser.close()
