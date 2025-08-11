# Python
from urllib.parse import quote

def format_card_heading(card) -> str:
    """
    Returns the heading text; if card.number exists, link to the specified URL.
    """
    if getattr(card, "number", None):
        frag = quote(str(card.number), safe="")
        return f"[{card.name}](https://ssimeonoff.github.io/cards-list#{frag})"
    return card.name
