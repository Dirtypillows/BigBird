"""On-demand deal analysis: fetches a listing's thread page and asks an LLM
to extract the price/item count and judge whether it's a good deal.

Deliberately not run automatically for every listing -- that would mean a
network fetch plus an LLM call per row, which doesn't scale and costs money
for listings nobody cares about. It's only triggered per-listing, when the
user clicks "Check Deal" on one they're actually interested in, and the
result is cached in the DB so re-viewing a checked listing never re-fetches
or re-calls the API.

There's no local market-price data to compare against, so a rule-based
"is this a good deal" heuristic would just be guessing. An LLM actually has
broad knowledge of typical resale value for the kinds of things these
forums sell (camera gear, car parts), so it does both the extraction (price,
item count -- more robust than per-site regex/selectors, since real threads
are messy: multi-item "parts out" listings, prices only in the first post,
SOLD/pending markers on individual items) and the judgment in one call.
"""

import os

import anthropic
from bs4 import BeautifulSoup

DEFAULT_MODEL = os.environ.get("BIGBIRD_DEAL_MODEL", "claude-haiku-4-5-20251001")
RATINGS = ("Excellent", "Great", "Fair", "Bad")

_TOOL = {
    "name": "report_deal_assessment",
    "description": "Report the extracted price, item count, and deal-quality rating for a marketplace listing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "price": {
                "type": ["string", "null"],
                "description": (
                    "The asking price as stated in the listing, kept short for display "
                    "(e.g. '$165', '$100-$2500 (16 items)'). Null if no price is stated "
                    "anywhere in the listing."
                ),
            },
            "item_count": {
                "type": ["integer", "null"],
                "description": (
                    "How many distinct items are being sold together in this listing. "
                    "1 for a single item. Null if genuinely unclear."
                ),
            },
            "rating": {
                "type": "string",
                "enum": list(RATINGS),
                "description": (
                    "How good a deal this is for a buyer, weighing the total asking price "
                    "against typical resale/market value for this kind of item -- and for "
                    "bundles, the combined value of everything included."
                ),
            },
            "reason": {
                "type": "string",
                "description": "One brief sentence explaining the rating.",
            },
        },
        "required": ["rating", "reason"],
    },
}


class DealCheckError(Exception):
    pass


def extract_page_text(html: str, max_chars: int = 12000) -> str:
    """Strip obvious chrome (nav/header/footer/script/style) and collapse to
    plain text. Verified against real fredmiranda and golfmk7 thread pages:
    the actual listing content (price, condition, description) reliably
    survives near the top of the result on both, despite very different
    markup -- old table layout vs a modern forum with heavy nav/menu chrome.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "svg", "noscript", "nav", "header", "footer", "form"]):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text(separator="\n").splitlines())
    return "\n".join(line for line in lines if line)[:max_chars]


def analyze_deal(title: str, site: str, page_text: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise DealCheckError("ANTHROPIC_API_KEY is not set -- set it in your environment to enable deal checking.")

    prompt = (
        f"Site: {site}\n"
        f"Listing title: {title}\n\n"
        "Below is the raw text of this listing's forum thread page (it may include some "
        "site navigation/chrome noise before or after the actual post -- ignore that and "
        "focus on the real listing content, usually the original poster's message):\n\n"
        f"---\n{page_text}\n---\n\n"
        "Extract the asking price and how many distinct items are included, then rate "
        "whether this is an Excellent, Great, Fair, or Bad deal for a buyer, based on "
        "typical resale/market value for this kind of item."
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=500,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "report_deal_assessment"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        raise DealCheckError(f"deal analysis failed: {e}") from e

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise DealCheckError("model didn't return a structured assessment")

    result = tool_use.input
    if result.get("rating") not in RATINGS:
        raise DealCheckError(f"model returned an unexpected rating: {result.get('rating')!r}")

    return {
        "price": result.get("price"),
        "item_count": result.get("item_count"),
        "rating": result["rating"],
        "reason": result.get("reason", ""),
    }
