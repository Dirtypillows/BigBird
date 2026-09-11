# bigbird

Universal forum listing search tool. Crawls public buy/sell forums and
indexes listings locally (SQLite + FTS5) so they can be searched
independently of the forum's own search.

## Phase 4 (current): pywebview desktop shell

```bash
python -m bigbird.desktop
```

Opens a native window (`bigbird/desktop.py`, via pywebview) running the FastAPI
backend on a background thread and loading its UI (`bigbird/static/`: a plain
HTML/CSS/JS page, no framework) -- a site picker + page count + Fetch button,
a search box, and a results list. Closing the window shuts the backend down.

**Bug found and fixed:** searching for anything containing a hyphen, quote,
or colon (`leica m-11`, `50mm f/1.4`, `canon:5d`) 500'd -- FTS5's `MATCH`
syntax treats those characters as query operators, so ordinary search terms
raised a syntax error server-side. `store._sanitize_fts_query` now wraps each
whitespace-separated token in its own quoted phrase before it reaches FTS5,
so special characters are searched literally instead of parsed as syntax,
while a space between tokens still means AND (unchanged behavior for plain
words). The frontend also had no error handling on the search path (unlike
fetch), so that 500 failed silently and just left the previous results on
screen with no sign anything had gone wrong -- looked exactly like "search
doesn't update." Both `runSearch()` and `/api/search` now handle failure
visibly instead of silently.

**Sort by recency, and a "Hide Sold" filter:** results default-sort by last
activity, newest first (`listings.last_post_ts`, an epoch second column).
Getting a real timestamp differs by site: golfmk7's XenForo markup has an
actual `data-time` epoch attribute on the post-date element
(`last_post_ts_field` in its profile), but fredmiranda only ever shows a
relative string ("2 hours", "6 years") with no absolute timestamp anywhere
in the page -- for that case `parse._parse_relative_time` estimates an
epoch by subtracting the parsed elapsed time from "now" at fetch time. Rows
indexed before this change have `last_post_ts = NULL` (added via an
idempotent `ALTER TABLE`) and sort to the bottom until re-fetched. The
"Hide Sold" checkbox in the UI filters out any title matching `\bsold\b`
(case-insensitive, so "Unsold" isn't wrongly excluded) client-side against
the already-fetched results -- no extra request, and it re-filters
instantly on toggle without needing to search again.

**Per-listing "Check Deal" button (price + Excellent/Great/Fair/Bad rating):**
the board-page listing has no price -- it's "usually found in the forum
thread itself" (confirmed against real thread pages on both sites: fredmiranda
has a structured `Price: $165.00` line in the first post; golfmk7 threads are
often multi-item "parts out" posts with a per-item price list, no single
total). And there's no real market-price data anywhere locally to judge
"is this a good deal" against -- a rule-based heuristic here would just be
guessing. So `bigbird/deal.py` fetches the listing's actual thread page
(`fetch.fetch_single`, reusing the same per-site fetch method/retry/backoff
as the board crawler) and hands the page text to an LLM (Anthropic API,
default model `claude-haiku-4-5-20251001`, overridable via
`BIGBIRD_DEAL_MODEL`) with a forced tool call, asking it to extract the
price and item count *and* rate the deal in one pass -- more robust than
per-site price regex/selectors, since real threads are messy (prices only
in the first post, multiple items each individually priced, SOLD/pending
markers on individual items within a bundle).

This never runs automatically -- only when the user clicks "Check Deal" on
a specific listing, since it costs a network fetch plus an API call. Once
checked, the result (`price`, `item_count`, `deal_rating`, `deal_reason`,
`checked_at`) is cached on that row in the DB, so re-viewing or re-searching
a checked listing never re-fetches the page or re-calls the API -- the
button is simply replaced by a colored rating badge (hover for the reason).

Requires an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # PowerShell: $env:ANTHROPIC_API_KEY = "sk-ant-..."
```

Without it, clicking "Check Deal" fails cleanly with a clear inline error
(verified: the thread page still gets fetched for real; only the LLM step
is short-circuited) rather than crashing -- the button resets to "Error -
retry". The live LLM call itself couldn't be verified from the dev sandbox
this was built in (no API key available there); everything up to that
boundary -- thread fetching, text extraction, caching, the button/badge UI,
and the no-key error path -- was tested against the real, running app.

## Phase 3: FastAPI backend

`bigbird/api.py` wraps the same fetch/parse/store/search building blocks
the CLI uses in a local HTTP API.

- `GET /api/profiles` -- list configured site profiles
- `GET /api/stats` -- listing counts per site
- `GET /api/search?q=...&limit=25` -- FTS5 search across every indexed site
- `POST /api/fetch` -- `{"site_id": "fredmiranda", "pages": 3}`, runs a real
  crawl synchronously and returns pages fetched / listings stored

Auto-generated interactive docs at `/docs`.

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

See the original build brief for the full 7-phase plan: PyInstaller
packaging is next.
