"""Generic, profile-driven page fetcher.

Supports two fetch methods, selected per-profile:
  - "httpx": plain HTTP GET with browser-like headers. Fast and light.
  - "playwright": drives a real Chromium. Needed for sites like
    fredmiranda.com, where Cloudflare fingerprints the TLS/HTTP-2 handshake
    and 403s plain httpx requests even with headers identical to a working
    curl request. Each page is fetched in its own fresh browser context,
    which avoids some session-based risk scoring.

Both methods share a RateLimiter (see bigbird/ratelimit.py): a 403/429/5xx,
or a connection-level failure (refused/reset/timeout), backs the pacing off
for every subsequent page, not just a same-page retry. This is what
golfmk7.com's bot-mitigation layer needed -- it started refusing connections
outright after a burst of requests at a fixed pace.
"""

import time

import httpx
from playwright.sync_api import Error as PlaywrightError

from bigbird.profile import Profile
from bigbird.ratelimit import RETRYABLE_STATUS, RateLimiter

MAX_ATTEMPTS = 5


def page_url(profile: Profile, page: int) -> str:
    """Map a 1-based page number to this profile's URL pattern."""
    if page < 1:
        raise ValueError("page must be >= 1")
    if page == 1:
        return profile.base_url + profile.board.first_page_url
    n = page + profile.board.page_offset
    return profile.base_url + profile.board.page_url_template.format(n=n)


def _fetch_one_httpx(client: httpx.Client, url: str, limiter: RateLimiter) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.get(url)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            limiter.on_blocked()
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"failed to fetch {url} after {MAX_ATTEMPTS} attempts: {e}") from e
            print(f"  ...connection issue fetching {url} ({e}); backing off to {limiter.delay:.1f}s")
            limiter.wait()
            continue

        if resp.status_code in RETRYABLE_STATUS:
            limiter.on_blocked()
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"failed to fetch {url} after {MAX_ATTEMPTS} attempts: HTTP {resp.status_code}")
            print(f"  ...got HTTP {resp.status_code} fetching {url}; backing off to {limiter.delay:.1f}s")
            limiter.wait()
            continue

        resp.raise_for_status()
        limiter.on_success()
        return resp.text

    raise RuntimeError(f"failed to fetch {url}: exhausted retries")  # unreachable


def _fetch_pages_httpx(profile: Profile, pages: int, limiter: RateLimiter):
    headers = {
        "User-Agent": profile.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(headers=headers, timeout=15.0, follow_redirects=True) as client:
        for page in range(1, pages + 1):
            url = page_url(profile, page)
            yield page, _fetch_one_httpx(client, url, limiter)
            if page < pages:
                limiter.wait()


def _fetch_one_playwright(browser, url: str, user_agent: str, limiter: RateLimiter) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        context = browser.new_context(user_agent=user_agent)
        try:
            page_obj = context.new_page()
            try:
                response = page_obj.goto(url, wait_until="domcontentloaded")
            except PlaywrightError as e:
                limiter.on_blocked()
                if attempt == MAX_ATTEMPTS:
                    raise RuntimeError(f"failed to fetch {url} after {MAX_ATTEMPTS} attempts: {e}") from e
                print(f"  ...connection issue fetching {url} ({e}); backing off to {limiter.delay:.1f}s")
                limiter.wait()
                continue

            status = response.status if response else None
            if status is None or status in RETRYABLE_STATUS:
                limiter.on_blocked()
                if attempt == MAX_ATTEMPTS:
                    raise RuntimeError(f"failed to fetch {url} after {MAX_ATTEMPTS} attempts: HTTP {status}")
                print(f"  ...got HTTP {status} fetching {url}; backing off to {limiter.delay:.1f}s")
                limiter.wait()
                continue

            if status >= 400:
                raise RuntimeError(f"failed to fetch {url}: HTTP {status}")

            limiter.on_success()
            return page_obj.content()
        finally:
            context.close()

    raise RuntimeError(f"failed to fetch {url}: exhausted retries")  # unreachable


def _fetch_pages_playwright(profile: Profile, pages: int, limiter: RateLimiter):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for page in range(1, pages + 1):
                url = page_url(profile, page)
                html = _fetch_one_playwright(browser, url, profile.user_agent, limiter)
                yield page, html
                if page < pages:
                    limiter.wait()
        finally:
            browser.close()


def fetch_single(profile: Profile, url: str) -> str:
    """Fetch one arbitrary URL (e.g. a thread page) using this profile's
    fetch method, retry/backoff, and User-Agent -- not a paginated crawl.
    """
    limiter = RateLimiter(base_delay=profile.request_delay_seconds)
    if profile.fetch_method == "httpx":
        headers = {
            "User-Agent": profile.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        with httpx.Client(headers=headers, timeout=15.0, follow_redirects=True) as client:
            return _fetch_one_httpx(client, url, limiter)
    elif profile.fetch_method == "playwright":
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                return _fetch_one_playwright(browser, url, profile.user_agent, limiter)
            finally:
                browser.close()
    else:
        raise ValueError(f"unknown fetch_method: {profile.fetch_method!r}")


def fetch_pages(profile: Profile, pages: int, delay_seconds: float | None = None):
    """Yield (page_number, html) for pages 1..pages, fetched one at a time.

    Pacing starts at delay_seconds (default: the profile's own
    request_delay_seconds) and adapts from there via a shared RateLimiter --
    slowing down when the site pushes back, easing back toward the baseline
    once several requests in a row succeed.
    """
    base_delay = profile.request_delay_seconds if delay_seconds is None else delay_seconds
    limiter = RateLimiter(base_delay=base_delay)
    if profile.fetch_method == "httpx":
        yield from _fetch_pages_httpx(profile, pages, limiter)
    elif profile.fetch_method == "playwright":
        yield from _fetch_pages_playwright(profile, pages, limiter)
    else:
        raise ValueError(f"unknown fetch_method: {profile.fetch_method!r}")
