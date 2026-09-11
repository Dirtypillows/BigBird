"""Per-site JSON profile schema.

A profile describes everything site-specific about crawling one forum
board: how to fetch pages, how to find each listing row in the HTML, and
how to pull fields out of a row. Field extraction supports what real forum
markup needs in practice (seen on fredmiranda.com): pulling a value from an
element found by position (`cell_index`) or CSS selector, from an attribute
instead of text content, and refining it with a regex.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FieldSpec:
    cell_index: int | None = None
    selector: str | None = None
    attribute: str | None = None
    regex: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "FieldSpec":
        return cls(
            cell_index=data.get("cell_index"),
            selector=data.get("selector"),
            attribute=data.get("attribute"),
            regex=data.get("regex"),
        )


@dataclass
class BoardConfig:
    first_page_url: str
    page_url_template: str
    page_offset: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "BoardConfig":
        return cls(
            first_page_url=data["first_page_url"],
            page_url_template=data["page_url_template"],
            page_offset=data.get("page_offset", 0),
        )


@dataclass
class ListingConfig:
    row_selector: str
    id_field: FieldSpec
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    url_template: str | None = None
    url_field: FieldSpec | None = None
    last_post_ts_field: FieldSpec | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ListingConfig":
        if not data.get("url_template") and not data.get("url_field"):
            raise ValueError("listing config needs one of url_template or url_field")
        return cls(
            row_selector=data["row_selector"],
            id_field=FieldSpec.from_dict(data["id_field"]),
            fields={name: FieldSpec.from_dict(spec) for name, spec in data["fields"].items()},
            url_template=data.get("url_template"),
            url_field=FieldSpec.from_dict(data["url_field"]) if "url_field" in data else None,
            last_post_ts_field=FieldSpec.from_dict(data["last_post_ts_field"]) if "last_post_ts_field" in data else None,
        )


@dataclass
class Profile:
    site_id: str
    name: str
    base_url: str
    fetch_method: str  # "httpx" | "playwright"
    board: BoardConfig
    listing: ListingConfig
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )
    request_delay_seconds: float = 1.5

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        return cls(
            site_id=data["site_id"],
            name=data["name"],
            base_url=data["base_url"].rstrip("/"),
            fetch_method=data["fetch_method"],
            board=BoardConfig.from_dict(data["board"]),
            listing=ListingConfig.from_dict(data["listing"]),
            user_agent=data.get("user_agent", cls.user_agent),
            request_delay_seconds=data.get("request_delay_seconds", cls.request_delay_seconds),
        )


def load_profile(path: str | Path) -> Profile:
    with open(path, encoding="utf-8") as f:
        return Profile.from_dict(json.load(f))
