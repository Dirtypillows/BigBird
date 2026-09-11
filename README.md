# bigbird

Universal forum listing search tool. Crawls public buy/sell forums and
indexes listings locally (SQLite + FTS5) so they can be searched
independently of the forum's own search.

## Phase 2 (current)

Sites are described by a JSON profile under `bigbird/profiles/` -- base
URL, pagination pattern, fetch method, and how to find/extract each
listing field. `bigbird/fetch.py` and `bigbird/parse.py` are generic and
driven entirely by whichever profile is passed in; adding a new site means
adding a new profile, not new code (unless the site needs an extraction
capability no existing profile uses yet).

`bigbird/profiles/fredmiranda.json` covers
[fredmiranda.com's Buy & Sell Photo-Gear board](https://www.fredmiranda.com/forum/board/10/),
the reference site so far:

- **fetch_method: "playwright"** -- fredmiranda.com sits behind Cloudflare,
  which fingerprints the TLS/HTTP-2 handshake. A plain `httpx` request gets
  a 403 even with full browser headers, while the same headers over `curl`
  succeed. Each page is fetched in its own fresh Chromium browser context
  with retry/backoff, which avoids Cloudflare's per-session risk scoring
  flagging the crawl. Other sites may work fine with `fetch_method: "httpx"`,
  which is faster and doesn't need a bundled browser.
- **Field extraction from attributes, not just text** -- the full listing
  title lives in a `title` HTML attribute (the visible link text gets
  truncated with "..."), and the topic id lives inside an `onclick` JS
  string rather than a clean link. Field specs support `cell_index` /
  `selector` to locate an element, `attribute` to pull from an attribute
  instead of its text, and `regex` to refine the extracted value.
- **Pagination offset** -- page 1 is a clean URL with no trailing segment;
  page 2+ appends `(page - 1)`. `board.page_offset` captures this per-site.

### Setup

```bash
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt
./.venv/Scripts/python -m playwright install chromium
```

### Usage

```bash
# fetch N board pages via a profile (default: fredmiranda) and index them
python -m bigbird.cli fetch --profile bigbird/profiles/fredmiranda.json --pages 10

# search the local index (FTS5 syntax: implicit AND, OR, quoted phrases, etc)
python -m bigbird.cli search "leica m11"
```

Data is stored in `data/bigbird.db` (gitignored). Listings are keyed by
`{site_id}:{native_id}` so multiple site profiles can share one database
without id collisions.

## Roadmap

See the original build brief for the full 7-phase plan: FastAPI backend,
pywebview desktop shell, and PyInstaller packaging. A second, structurally
different site profile hasn't been added yet -- the current profile schema
(fixed columns: title/author/replies/views/last_post) is shaped entirely by
what fredmiranda.com needs, and may need to flex once a second real site is
in hand.
