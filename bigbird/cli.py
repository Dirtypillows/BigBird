"""CLI: fetch a site via its JSON profile, then search the local index."""

import argparse
from pathlib import Path

from bigbird import fetch, parse, store
from bigbird.profile import load_profile

DEFAULT_PROFILE = Path(__file__).resolve().parent / "profiles" / "fredmiranda.json"


def cmd_fetch(args: argparse.Namespace) -> None:
    profile = load_profile(args.profile)
    conn = store.connect(args.db)
    total = 0
    for page, html in fetch.fetch_pages(profile, args.pages, delay_seconds=args.delay):
        listings = parse.parse_board_page(profile, html)
        stored = store.upsert_listings(conn, profile.site_id, page, listings)
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
        print(f"[{r['site']}] {r['title']}")
        print(f"  by {r['author']} | {r['replies']} replies | {r['views']} views | {r['last_post']}")
        print(f"  {r['url']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(prog="bigbird")
    parser.add_argument("--db", type=str, default=str(store.DEFAULT_DB_PATH), help="path to sqlite db")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="fetch and index a site via its JSON profile")
    fetch_p.add_argument("--profile", type=str, default=str(DEFAULT_PROFILE), help="path to a site profile JSON file")
    fetch_p.add_argument("--pages", type=int, default=1, help="number of board pages to fetch")
    fetch_p.add_argument("--delay", type=float, default=None, help="seconds between page requests (default: profile's)")
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
