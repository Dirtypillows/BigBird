# bigbird

Universal forum listing search tool. Crawls public buy/sell forums and
indexes listings locally (SQLite + FTS5) so they can be searched
independently of the forum's own search.

## Phase 3 (current): FastAPI backend

`bigbird/api.py` wraps the same fetch/parse/store/search building blocks
the CLI uses in a local HTTP API -- the interface the pywebview desktop
shell (next phase) will talk to.

```bash
python -m uvicorn bigbird.api:app --port 8000
```

- `GET /api/profiles` -- list configured site profiles
- `GET /api/stats` -- listing counts per site
- `GET /api/search?q=...&limit=25` -- FTS5 search across every indexed site
- `POST /api/fetch` -- `{"site_id": "fredmiranda", "pages": 3}`, runs a real
  crawl synchronously and returns pages fetched / listings stored

Auto-generated interactive docs at `/docs`. All verified live: `/api/fetch`
was run against fredmiranda.com through the API (not just the CLI) and
`/api/stats` reflected the new count afterward.

## Phase 2

Sites are described by a JSON profile under `bigbird/profiles/` -- base
URL, pagination pattern, fetch method, and how to find/extract each
listing field. `bigbird/fetch.py` and `bigbird/parse.py` are generic and
driven entirely by whichever profile is passed in; adding a new site means
adding a new profile, not new code (unless the site needs an extraction
capability no existing profile uses yet).

Two profiles exist so far, on two structurally different forum engines:

**`bigbird/profiles/fredmiranda.json`** --
[fredmiranda.com's Buy & Sell Photo-Gear board](https://www.fredmiranda.com/forum/board/10/),
old-school table markup:

- **fetch_method: "playwright"** -- sits behind Cloudflare, which
  fingerprints the TLS/HTTP-2 handshake. A plain `httpx` request gets a 403
  even with full browser headers, while the same headers over `curl`
  succeed.
- **Field extraction from attributes, not just text** -- the full listing
  title lives in a `title` HTML attribute (the visible link text gets
  truncated with "..."), and the topic id lives inside an `onclick` JS
  string rather than a clean link.
- **Pagination offset** -- page 1 is a clean URL with no trailing segment;
  page 2+ appends `(page - 1)`. `board.page_offset` captures this per-site.
- Listing URLs are id-only (`/forum/topic/{id}/`), so `url_template`
  reconstructs them from the extracted id.

**`bigbird/profiles/golfmk7.json`** --
[golfmk7.com's Private Classifieds board](https://www.golfmk7.com/forums/index.php?forums/private-classifieds-buy-sell-and-trade.184/),
a XenForo forum, class-based div markup:

- **fetch_method: "playwright"** -- fronted by a different bot-mitigation
  layer (returns "Access Denied: Browser Verification Failed" to plain
  `curl`/`httpx`, even with full browser headers); Playwright passes.
  Its bot mitigation also appears to temporarily rate-limit an IP after a
  burst of automated requests (seen as connection refusals during
  back-to-back manual test runs) -- another reason to keep request pacing
  conservative regardless of whether a site publishes a robots.txt.
- **Field selectors need no `cell_index` or `attribute`/`regex` tricks** --
  clean, purpose-named CSS classes (`.structItem-title`, `a.username`,
  `.structItem-cell--meta dl:nth-of-type(n) dd`) cover every field with
  plain selectors.
- **Listing URLs need the real link, not just the id** -- thread URLs are
  slug-based (`/threads/some-title-slug.472745/`); reconstructing from the
  numeric id alone drops the slug. This is what motivated adding
  `url_field` (extract the actual `href` from the row and resolve it
  against `base_url`) as an alternative to `url_template` -- the one real
  schema change this second site required.

### Adaptive rate limiting

`bigbird/ratelimit.py` provides a `RateLimiter` shared across a whole crawl
(see `bigbird/fetch.py`). A 403/408/429/5xx response, or a connection-level
failure (refused/reset/timeout), doubles the delay before the next request
(capped at 120s) and retries -- up to 5 attempts per page before giving up
with a clear error. After 5 consecutive successful requests, the delay
eases back down 20% toward the profile's baseline, so a temporary slowdown
doesn't permanently throttle a long crawl. This is what golfmk7.com's
connection refusals (seen while stress-testing that profile) called for:
back off automatically when a site is telling us to slow down, rather than
hammering it at a fixed pace until it starts failing outright.

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
python -m bigbird.cli fetch --profile bigbird/profiles/golfmk7.json --pages 5

# search the local index across every indexed site (FTS5 syntax: implicit
# AND, OR, quoted phrases, etc)
python -m bigbird.cli search "leica m11"
```

Data is stored in `data/bigbird.db` (gitignored). Listings are keyed by
`{site_id}:{native_id}` so multiple site profiles share one database
without id collisions.

## Roadmap

See the original build brief for the full 7-phase plan: pywebview desktop
shell and PyInstaller packaging are next.
