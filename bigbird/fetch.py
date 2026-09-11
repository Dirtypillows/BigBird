"""Generic, profile-driven page fetcher.

Supports two fetch methods, selected per-profile:
  - "httpx": plain HTTP GET with browser-like headers. Fast and light.
  - "playwright": drives a real Chromium. Needed for sites like
    fredmiranda.com, where Cloudflare fingerprints the TLS/HTTP-2 handshake
    and 403s plain httpx requests even with headers identical to a working
    curl request. Each page is fetched in its own fresh browser context
    with retry/backoff, which avoids Cloudflare's per-session risk scoring
    flagging the crawl.
"""

import time

import httpx

from bigbird.profile import Profile


def page_url(profile: Profile, page: int) -> str:
    """Map a 1-based page number to this profile's URL pattern."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if page == 1:
        return profile.base_url + profile.board.first_page_url
    n = page + profile.board.page_offset
    return profile.base_url + profile.board.page_url_template.format(n=n)


def _fetch_pages_httpx(profile: Profile, pages: int, delay_seconds: float):
    headers = {
        "User-Agent": profile.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(headers=headers, timeout=15.0, follow_redirects=True) as client:
        for page in range(1, pages + 1):
            url = page_url(profile, page)
            resp = client.get(url)
            resp.raise_for_status()
            yield page, resp.text
            if page < pages:
                time.sleep(delay_seconds)


def _fetch_one_playwright(browser, url: str, user_agent: str, retries: int = 3, backoff_seconds: float = 5.0) -> str:
    """Fetch a single URL in its own fresh browser context.

    A fresh context per page (rather than reusing one context/page across
    the whole crawl) keeps each request looking like an independent visit,
    which noticeably reduces 403s from Cloudflare's session risk scoring.
    """
    last_status = None
    for attempt in range(1, retries + 1):
        context = browser.new_context(user_agent=user_agent)
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


def _fetch_pages_playwright(profile: Profile, pages: int, delay_seconds: float):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for page in range(1, pages + 1):
                url = page_url(profile, page)
                html = _fetch_one_playwright(browser, url, profile.user_agent)
                yield page, html
                if page < pages:
                    time.sleep(delay_seconds)
        finally:
            browser.close()


def fetch_pages(profile: Profile, pages: int, delay_seconds: float | None = None):
    """Yield (page_number, html) for pages 1..pages, fetched one at a time."""
    delay = profile.request_delay_seconds if delay_seconds is None else delay_seconds
    if profile.fetch_method == "httpx":
        yield from _fetch_pages_httpx(profile, pages, delay)
    elif profile.fetch_method == "playwright":
        yield from _fetch_pages_playwright(profile, pages, delay)
    else:
        raise ValueError(f"unknown fetch_method: {profile.fetch_method!r}")
