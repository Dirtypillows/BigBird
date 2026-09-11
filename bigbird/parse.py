"""Phase 1: hardcoded parser for fredmiranda.com's Buy & Sell Photo-Gear board.

The board is old-school table markup (no useful classes/ids on the table
itself). Each listing row is a <tr valign="top"> whose second <td> carries
both the full untruncated title (as a `title` attribute -- the anchor text
inside gets truncated with "..." for long titles) and an onClick handler
containing the topic id.
"""

import re

from bs4 import BeautifulSoup

TOPIC_ID_RE = re.compile(r"/forum/topic/(\d+)")


def _clean(text: str) -> str:
    return text.replace("\xa0", " ").strip()


def parse_board_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    for row in soup.find_all("tr", valign="top"):
        tds = row.find_all("td", recursive=False)
        if len(tds) < 6:
            continue

        title_td = tds[1]
        onclick = title_td.get("onclick") or ""
        match = TOPIC_ID_RE.search(onclick)
        if not match:
            continue

        topic_id = int(match.group(1))
        title = _clean(title_td.get("title", ""))
        if not title:
            continue

        author_link = tds[2].find("a")
        author = _clean(author_link.get_text()) if author_link else ""

        listings.append(
            {
                "topic_id": topic_id,
                "title": title,
                "url": f"https://www.fredmiranda.com/forum/topic/{topic_id}/",
                "author": author,
                "replies": _clean(tds[3].get_text()),
                "views": _clean(tds[4].get_text()),
                "last_post": _clean(tds[5].get_text()),
            }
        )

    return listings
