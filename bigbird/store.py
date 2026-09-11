"""SQLite + FTS5 storage for parsed listings."""

import datetime
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bigbird.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    topic_id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
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
    topic_id UNINDEXED
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
        conn.execute(
            """
            INSERT INTO listings (topic_id, site, title, url, author, replies, views, last_post, board_page, fetched_at)
            VALUES (:topic_id, :site, :title, :url, :author, :replies, :views, :last_post, :board_page, :fetched_at)
            ON CONFLICT(topic_id) DO UPDATE SET
                title=excluded.title,
                url=excluded.url,
                author=excluded.author,
                replies=excluded.replies,
                views=excluded.views,
                last_post=excluded.last_post,
                board_page=excluded.board_page,
                fetched_at=excluded.fetched_at
            """,
            {**listing, "site": site, "board_page": page, "fetched_at": now},
        )
        conn.execute("DELETE FROM listings_fts WHERE topic_id = ?", (listing["topic_id"],))
        conn.execute(
            "INSERT INTO listings_fts (title, author, topic_id) VALUES (?, ?, ?)",
            (listing["title"], listing["author"], listing["topic_id"]),
        )
        count += 1
    conn.commit()
    return count


def search(conn: sqlite3.Connection, query: str, limit: int = 25) -> list[dict]:
    rows = conn.execute(
        """
        SELECT l.title, l.url, l.author, l.replies, l.views, l.last_post, l.site
        FROM listings_fts f
        JOIN listings l ON l.topic_id = f.topic_id
        WHERE listings_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    columns = ["title", "url", "author", "replies", "views", "last_post", "site"]
    return [dict(zip(columns, row)) for row in rows]
