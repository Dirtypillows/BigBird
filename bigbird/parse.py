"""Generic, profile-driven listing parser.

Walks the rows matched by a profile's `row_selector`, extracts the id field
(skipping rows that don't have one -- header/pagination rows), and extracts
each configured field the same way.
"""

import re

from bs4 import BeautifulSoup

from bigbird.profile import FieldSpec, Profile


def _clean(text: str) -> str:
    return text.replace("\xa0", " ").strip()


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

        record["url"] = profile.listing.url_template.format(base_url=profile.base_url, id=native_id)
        listings.append(record)

    return listings
