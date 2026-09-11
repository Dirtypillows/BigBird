"""Generic, profile-driven listing parser.

Walks the rows matched by a profile's `row_selector`, extracts the id field
(skipping rows that don't have one -- header/pagination rows), and extracts
each configured field the same way.
"""

import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from bigbird.profile import FieldSpec, Profile

_RELATIVE_TIME_UNITS = {
    "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "hour": 3600, "hours": 3600,
    "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
    "month": 2629800, "months": 2629800,  # average month, ok for approximate sorting
    "year": 31557600, "years": 31557600,  # 365.25 days, ok for approximate sorting
}
_RELATIVE_TIME_RE = re.compile(r"(\d+)\s*([a-zA-Z]+)")


def _clean(text: str) -> str:
    return text.replace("\xa0", " ").strip()


def _parse_relative_time(text: str) -> int | None:
    """Best-effort: turn "2 hours", "10 secs", "6 years" into an epoch estimate.

    Some sites (fredmiranda.com) only ever display a relative "time ago"
    string for the last post, with no absolute timestamp anywhere in the
    markup -- there's nothing more precise to sort by. Anchoring to "now"
    at parse time is approximate (accurate to whenever the page was
    actually fetched, not to the second), but that's enough for a
    recency-ordered results list.
    """
    match = _RELATIVE_TIME_RE.search(text or "")
    if not match:
        return None
    seconds_per_unit = _RELATIVE_TIME_UNITS.get(match.group(2).lower())
    if seconds_per_unit is None:
        return None
    return int(time.time() - int(match.group(1)) * seconds_per_unit)


def _extract(spec: FieldSpec, row) -> str | None:
    el = row
    if spec.cell_index is not None:
        cells = row.find_all("td", recursive=False)
        if spec.cell_index >= len(cells):
            return None
        el = cells[spec.cell_index]

    if spec.selector:
        el = el.select_one(spec.selector)
        if el is None:
            return None

    value = el.get(spec.attribute, "") if spec.attribute else el.get_text()
    value = _clean(value)

    if spec.regex:
        match = re.search(spec.regex, value)
        if not match:
            return None
        value = match.group(1)

    return value


def parse_board_page(profile: Profile, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    for row in soup.select(profile.listing.row_selector):
        native_id = _extract(profile.listing.id_field, row)
        if not native_id:
            continue

        record = {"id": native_id}
        for name, spec in profile.listing.fields.items():
            record[name] = _extract(spec, row) or ""

        if not record.get("title"):
            continue

        if profile.listing.url_field is not None:
            href = _extract(profile.listing.url_field, row)
            if not href:
                continue
            record["url"] = urljoin(profile.base_url + "/", href)
        else:
            record["url"] = profile.listing.url_template.format(base_url=profile.base_url, id=native_id)

        last_post_ts = None
        if profile.listing.last_post_ts_field is not None:
            raw_ts = _extract(profile.listing.last_post_ts_field, row)
            if raw_ts:
                try:
                    last_post_ts = int(float(raw_ts))
                except ValueError:
                    last_post_ts = None
        if last_post_ts is None:
            last_post_ts = _parse_relative_time(record.get("last_post", ""))
        record["last_post_ts"] = last_post_ts

        listings.append(record)

    return listings
