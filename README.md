# bigbird

Universal forum listing search tool. Crawls public buy/sell forums and
indexes listings locally (SQLite + FTS5) so they can be searched
independently of the forum's own search.

## Phase 1 (current)

Hardcoded, single-site pipeline against fredmiranda.com's
[Buy & Sell Photo-Gear board](https://www.fredmiranda.com/forum/board/10/),
proving out fetch -> parse -> store -> search before generalizing to
per-site JSON profiles.

fredmiranda.com sits behind Cloudflare, which fingerprints the TLS/HTTP-2
handshake -- a plain `httpx` request gets a 403 even with full browser
headers, while the same headers over `curl` succeed. So Phase 1 fetches
with Playwright (real Chromium) instead, per the brief's httpx-with-
Playwright-fallback design. Each page is fetched in its own fresh browser
context with retry/backoff, which avoids Cloudflare's per-session risk
scoring flagging the crawl.

### Setup

```bash
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt
./.venv/Scripts/python -m playwright install chromium
```

### Usage

```bash
# fetch N board pages (100 listings/page) and index them
python -m bigbird.cli fetch --pages 3

# search the local index (FTS5 syntax: implicit AND, OR, quoted phrases, etc)
python -m bigbird.cli search "leica m11"
```

Data is stored in `data/bigbird.db` (gitignored).

## Roadmap

See the original build brief for the full 7-phase plan: generalizing to a
per-site JSON profile schema, FastAPI backend, pywebview desktop shell, and
PyInstaller packaging.
