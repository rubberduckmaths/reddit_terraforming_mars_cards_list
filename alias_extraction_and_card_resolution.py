import re
import json
from typing import Iterable, List, Tuple, Set

from card_data_model import Card

# Match [ALIAS] but not markdown link text [text](url)
# (?!\() ensures ']' isn't immediately followed by '('
BRACKETED_ALIAS_RE = re.compile(r"\[([^\[\]\n]{1,40})\](?!\()")


def extract_aliases(body: str) -> List[str]:
    """
    Extract potential aliases from bracketed text while avoiding markdown links.
    """
    if not body:
        return []
    candidates = [m.group(1).strip() for m in BRACKETED_ALIAS_RE.finditer(body)]
    # Filter out trivial tokens like empty strings or obvious non-alias noise
    cleaned = []
    for c in candidates:
        # ignore tokens that look like URLs or markdown artifacts
        if "http://" in c or "https://" in c:
            continue
        # keep reasonable tokens
        if 1 <= len(c) <= 40:
            cleaned.append(c)
    return cleaned


def _normalize_tags(raw_tags: List[str]) -> List[str]:
    """
    Normalize tags to a clean list of Title Cased strings.
    Handles cases where tags might contain a single JSON-like array string.
    """
    if not raw_tags:
        return []

    # If it's a single JSON-like array string, parse it
    if len(raw_tags) == 1:
        s = (raw_tags[0] or "").strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(t).strip().strip('"').strip("'").title() for t in parsed if str(t).strip()]
            except Exception:
                pass  # fall through to generic handling

    # Generic handling: split items that still contain brackets/commas
    out: List[str] = []
    for item in raw_tags:
        if not item:
            continue
        text = str(item).strip()
        # Strip outer brackets if present
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
        # Split by comma and clean quotes/spaces
        parts = [p.strip().strip('"').strip("'") for p in text.split(",")]
        for p in parts:
            if p:
                out.append(p.title())
    return out


def format_card_reply(cards: List[Card], footer: str = "") -> str:
    """
    Format a reply message for one or more cards.
    - Skip the cost line if cost is "N/A" (case-insensitive) or empty.
    - If the cost is numeric, suffix it with "MC" (no space).
    - Use double line breaks between each section.
    - Print tags as comma-separated text in Title Case; skip if there are no tags.
    - Render the card name in bold (Reddit markdown).
    """
    blocks: List[str] = []
    for c in cards:
        sections: List[str] = []

        # Card name (bold)
        sections.append(f"Card: **{c.name}**")

        # Cost handling
        cost_raw = (c.cost or "").strip()
        if cost_raw and cost_raw.lower() != "n/a":
            cost_display = f"{cost_raw}MC" if cost_raw.isdigit() else cost_raw
            sections.append(f"Cost: {cost_display}")

        # Description
        sections.append(f"Description: {c.description}")

        # Tags: normalize and join
        pretty_tags = _normalize_tags(list(c.tags or []))
        if pretty_tags:
            sections.append(f"Tags: {', '.join(pretty_tags)}")

        # Join sections with double line breaks
        blocks.append("\n\n".join(sections))

    reply = "\n\n----\n\n".join(blocks)  # separate cards clearly with a divider and double breaks
    if footer:
        reply = f"{reply}\n\n{footer}"
    return reply


def resolve_cards_for_comment(text: str, lookup_fn) -> List[Card]:
    """
    From a comment text, extract aliases and resolve them to cards (deduped, in appearance order).
    lookup_fn: function(str) -> Card | None
    """
    tokens = extract_aliases(text)
    seen: Set[str] = set()
    resolved: List[Card] = []
    for tok in tokens:
        key = " ".join(tok.strip().split()).upper()
        if key in seen:
            continue
        seen.add(key)
        card = lookup_fn(tok)
        if card:
            # Avoid duplicates if multiple aliases map to the same card
            if all(card.name != c.name for c in resolved):
                resolved.append(card)
    return resolved
