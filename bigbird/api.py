"""FastAPI backend: exposes the crawler engine and search index over HTTP,
and serves the desktop shell's UI as static files from the same origin
(so the frontend can call the API with plain relative fetch() calls, no
CORS setup needed).

This is what the pywebview desktop shell talks to. Kept deliberately thin
-- it's the same fetch/parse/store/search building blocks the CLI already
uses, just callable from an HTTP client instead of a terminal.
"""

import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bigbird import deal, fetch, parse, store
from bigbird.profile import load_profile

PROFILES_DIR = Path(__file__).resolve().parent / "profiles"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="bigbird")


def _profile_path(site_id: str) -> Path:
    path = PROFILES_DIR / f"{site_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"unknown profile: {site_id}")
    return path


@app.get("/api/profiles")
def list_profiles():
    profiles = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        profile = load_profile(path)
        profiles.append({"site_id": profile.site_id, "name": profile.name, "base_url": profile.base_url})
    return profiles


@app.get("/api/stats")
def stats():
    conn = store.connect()
    rows = conn.execute("SELECT site, COUNT(*) FROM listings GROUP BY site").fetchall()
    conn.close()
    return [{"site": site, "count": count} for site, count in rows]


@app.get("/api/search")
def search(q: str, limit: int = 25):
    conn = store.connect()
    try:
        return store.search(conn, q, limit=limit)
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=400, detail=f"bad search query: {e}") from e
    finally:
        conn.close()


class FetchRequest(BaseModel):
    site_id: str
    pages: int = 1


@app.post("/api/fetch")
def run_fetch(req: FetchRequest):
    profile = load_profile(_profile_path(req.site_id))
    conn = store.connect()
    pages_fetched = 0
    listings_stored = 0
    try:
        for page, html in fetch.fetch_pages(profile, req.pages):
            listings = parse.parse_board_page(profile, html)
            listings_stored += store.upsert_listings(conn, profile.site_id, page, listings)
            pages_fetched += 1
    finally:
        conn.close()
    return {"site_id": req.site_id, "pages_fetched": pages_fetched, "listings_stored": listings_stored}


class CheckDealRequest(BaseModel):
    listing_id: str


@app.post("/api/check-deal")
def check_deal(req: CheckDealRequest):
    conn = store.connect()
    try:
        listing = store.get_listing(conn, req.listing_id)
        if listing is None:
            raise HTTPException(status_code=404, detail=f"unknown listing: {req.listing_id}")

        if listing["checked_at"]:
            return listing  # cached -- no re-fetch, no re-charging the API

        profile = load_profile(_profile_path(listing["site"]))
        try:
            html = fetch.fetch_single(profile, listing["url"])
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"couldn't fetch the listing page: {e}") from e

        page_text = deal.extract_page_text(html)
        try:
            result = deal.analyze_deal(listing["title"], listing["site"], page_text)
        except deal.DealCheckError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        store.save_deal_check(conn, req.listing_id, result["price"], result["item_count"], result["rating"], result["reason"])
        return store.get_listing(conn, req.listing_id)
    finally:
        conn.close()


# Mounted last so it never shadows the /api/* routes above.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
