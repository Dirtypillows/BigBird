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
    last_post_ts INTEGER,
    board_page INTEGER,
    fetched_at TEXT NOT NULL,
    price TEXT,
    item_count INTEGER,
    deal_rating TEXT,
    deal_reason TEXT,
    checked_at TEXT
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
    for ddl in (
        "ALTER TABLE listings ADD COLUMN last_post_ts INTEGER",
        "ALTER TABLE listings ADD COLUMN price TEXT",
        "ALTER TABLE listings ADD COLUMN item_count INTEGER",
        "ALTER TABLE listings ADD COLUMN deal_rating TEXT",
        "ALTER TABLE listings ADD COLUMN deal_reason TEXT",
        "ALTER TABLE listings ADD COLUMN checked_at TEXT",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # already present -- CREATE TABLE above only runs on a fresh db
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
            "last_post_ts": listing.get("last_post_ts"),
            "board_page": page,
            "fetched_at": now,
        }
        conn.execute(
            """
            INSERT INTO listings (listing_id, site, native_id, title, url, author, replies, views, last_post, last_post_ts, board_page, fetched_at)
            VALUES (:listing_id, :site, :native_id, :title, :url, :author, :replies, :views, :last_post, :last_post_ts, :board_page, :fetched_at)
            ON CONFLICT(listing_id) DO UPDATE SET
                title=excluded.title,
                url=excluded.url,
                author=excluded.author,
                replies=excluded.replies,
                views=excluded.views,
                last_post=excluded.last_post,
                last_post_ts=excluded.last_post_ts,
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


def get_listing(conn: sqlite3.Connection, listing_id: str) -> dict | None:
    columns = ["listing_id", "site", "title", "url", "price", "item_count", "deal_rating", "deal_reason", "checked_at"]
    row = conn.execute(
        f"SELECT {', '.join(columns)} FROM listings WHERE listing_id = ?",
        (listing_id,),
    ).fetchone()
    return dict(zip(columns, row)) if row else None


def save_deal_check(
    conn: sqlite3.Connection,
    listing_id: str,
    price: str | None,
    item_count: int | None,
    rating: str,
    reason: str,
) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE listings
        SET price = ?, item_count = ?, deal_rating = ?, deal_reason = ?, checked_at = ?
        WHERE listing_id = ?
        """,
        (price, item_count, rating, reason, now, listing_id),
    )
    conn.commit()


def _sanitize_fts_query(raw: str) -> str:
    """Turn free-typed user input into a query FTS5 can't choke on.

    FTS5's MATCH syntax treats -, ", :, (, ), * etc as operators, so plain
    search terms a user would reasonably type -- "leica m-11", "50mm f/1.4",
    "canon:5d" -- raise an FTS5 syntax error and 500 the request. Wrapping
    every whitespace-separated token in its own quoted phrase sidesteps
    that: quoted phrases are searched literally, not parsed for operators,
    while a space between them still means AND, so plain multi-word
    searches behave the same as before.
    """
    quote = '"'
    tokens = raw.split()
    if not tokens:
        return quote + quote
    return " ".join(quote + token.replace(quote, quote + quote) + quote for token in tokens)


def search(conn: sqlite3.Connection, query: str, limit: int = 25) -> list[dict]:
    columns = [
        "listing_id", "title", "url", "author", "replies", "views", "last_post", "last_post_ts",
        "site", "price", "item_count", "deal_rating", "deal_reason", "checked_at",
    ]
    rows = conn.execute(
        f"""
        SELECT {", ".join("l." + c for c in columns)}
        FROM listings_fts f
        JOIN listings l ON l.listing_id = f.listing_id
        WHERE listings_fts MATCH ?
        ORDER BY l.last_post_ts IS NULL, l.last_post_ts DESC
        LIMIT ?
        """,
        (_sanitize_fts_query(query), limit),
    ).fetchall()
    return [dict(zip(columns, row)) for row in rows]
