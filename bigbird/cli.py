"""CLI for Phase 1: fetch the hardcoded fredmiranda board, then search locally."""

import argparse
from pathlib import Path

from bigbird import fetch, parse, store


def cmd_fetch(args: argparse.Namespace) -> None:
    conn = store.connect(args.db)
    total = 0
    for page, html in fetch.fetch_pages(args.pages, delay_seconds=args.delay):
        listings = parse.parse_board_page(html)
        stored = store.upsert_listings(conn, fetch.SITE, page, listings)
        total += stored
        print(f"page {page}: parsed {len(listings)} listings, stored {stored}")
    print(f"done: {total} listings stored in {args.db}")


def cmd_search(args: argparse.Namespace) -> None:
    conn = store.connect(args.db)
    results = store.search(conn, args.query, limit=args.limit)
    if not results:
        print("no matches")
        return
    for r in results:
        print(f"{r['title']}")
        print(f"  by {r['author']} | {r['replies']} replies | {r['views']} views | {r['last_post']}")
        print(f"  {r['url']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(prog="bigbird")
    parser.add_argument("--db", type=str, default=str(store.DEFAULT_DB_PATH), help="path to sqlite db")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="fetch and index the hardcoded board")
    fetch_p.add_argument("--pages", type=int, default=1, help="number of board pages to fetch")
    fetch_p.add_argument("--delay", type=float, default=1.5, help="seconds between page requests")
    fetch_p.set_defaults(func=cmd_fetch)

    search_p = sub.add_parser("search", help="search locally indexed listings")
    search_p.add_argument("query", type=str, help="FTS5 query, e.g. 'leica lens'")
    search_p.add_argument("--limit", type=int, default=25)
    search_p.set_defaults(func=cmd_search)

    args = parser.parse_args()
    args.db = Path(args.db)
    args.func(args)


if __name__ == "__main__":
    main()
