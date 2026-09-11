"""SQLite + FTS5 storage for parsed listings, keyed per-site."""

import datetime
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bigbird.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id TEXT PRIMARY KEY,
    site TEXT NOT NULL,
    native_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    author TEXT,
    replies TEXT,
    views TEXT,
    last_post TEXT,
    board_page INTEGER,
    fetched_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS listings_fts USING fts5(
    title,
    author,
    listing_id UNINDEXED
);
"""


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def upsert_listings(conn: sqlite3.Connection, site: str, page: int, listings: list[dict]) -> int:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    count = 0
    for listing in listings:
        listing_id = f"{site}:{listing['id']}"
        row = {
            "listing_id": listing_id,
            "site": site,
            "native_id": listing["id"],
            "title": listing["title"],
            "url": listing["url"],
            "author": listing.get("author", ""),
            "replies": listing.get("replies", ""),
            "views": listing.get("views", ""),
            "last_post": listing.get("last_post", ""),
            "board_page": page,
            "fetched_at": now,
        }
        conn.execute(
            """
            INSERT INTO listings (listing_id, site, native_id, title, url, author, replies, views, last_post, board_page, fetched_at)
            VALUES (:listing_id, :site, :native_id, :title, :url, :author, :replies, :views, :last_post, :board_page, :fetched_at)
            ON CONFLICT(listing_id) DO UPDATE SET
                title=excluded.title,
                url=excluded.url,
                author=excluded.author,
                replies=excluded.replies,
                views=excluded.views,
                last_post=excluded.last_post,
                board_page=excluded.board_page,
                fetched_at=excluded.fetched_at
            """,
            row,
        )
        conn.execute("DELETE FROM listings_fts WHERE listing_id = ?", (listing_id,))
        conn.execute(
            "INSERT INTO listings_fts (title, author, listing_id) VALUES (?, ?, ?)",
            (row["title"], row["author"], listing_id),
        )
        count += 1
    conn.commit()
    return count


def search(conn: sqlite3.Connection, query: str, limit: int = 25) -> list[dict]:
    rows = conn.execute(
        """
        SELECT l.title, l.url, l.author, l.replies, l.views, l.last_post, l.site
        FROM listings_fts f
        JOIN listings l ON l.listing_id = f.listing_id
        WHERE listings_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    columns = ["title", "url", "author", "replies", "views", "last_post", "site"]
    return [dict(zip(columns, row)) for row in rows]
