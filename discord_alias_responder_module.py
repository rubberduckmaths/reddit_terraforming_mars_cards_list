# Python
# File: discord_alias_responder.py
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Iterable
from urllib.parse import quote

from card_loader_from_csv import load_cards_from_csv
from card_index_manager import CardIndex
from card_data_model import Card


TRIGGER_RE = re.compile(r"\[\[([^\[\]]+)\]\]")

logger = logging.getLogger(__name__)

# Basic sanitization for Discord to avoid accidental pings and formatting breaks
def _escape_discord(s: str) -> str:
    return (
        s.replace("@", "@\u200b")  # stop mentions
         .replace("`", "'")        # avoid code fence breaks
    )

def _format_tags(tags: Iterable[str]) -> str:
    # ["building", "power"] -> "Building, Power"
    pretty = [t.replace("_", " ").strip().title() for t in tags if t and t.strip()]
    return ", ".join(pretty).replace("[", "").replace("]", "").replace("\"", "")

def _format_heading(card: Card) -> str:
    # If card.number exists, link the heading; otherwise show plain name
    number = getattr(card, "number", None)
    name = _escape_discord(card.name)
    if number:
        return f"[{name}](https://ssimeonoff.github.io/cards-list{number})"
    return name

def _format_card_for_discord(card: Card) -> str:
    # Keep it concise and Discord-friendly
    heading = _format_heading(card)
    cost = _escape_discord(card.cost)
    tags = _format_tags(card.tags)
    desc = _escape_discord(card.description)

    # Bold heading; include cost, tags line if present; then description
    lines = [f"**{heading}**"]
    if cost:
        lines.append(f"Cost: {cost}")
    if tags:
        lines.append(f"Tags: {tags}")
    if desc:
        lines.append(desc)
    return "\n".join(lines)

@dataclass
class DiscordAliasResponder:
    index: CardIndex
    reply_footer: str = ""

    @classmethod
    def from_csv(cls, csv_path: str, reply_footer: str = "") -> "DiscordAliasResponder":
        cards = load_cards_from_csv(csv_path)
        index = CardIndex.build(cards)
        return cls(index=index, reply_footer=reply_footer or "")

    def _lookup(self, token: str) -> Optional[Card]:
        return self.index.lookup(token.strip())

    @staticmethod
    def extract_triggers(message: str) -> List[str]:
        # Returns tokens inside [[...]] in order of appearance
        return [m.group(1).strip() for m in TRIGGER_RE.finditer(message or "") if m.group(1).strip()]

    @staticmethod
    def _log_sanitized(prefix: str, text: str) -> None:
        if text is None:
            logger.debug("%s <none>", prefix)
            return
        # Avoid pings and huge payloads in logs
        safe = text.replace("@", "@\u200b").replace("\n", "\\n")
        if len(safe) > 300:
            safe = safe[:300] + "...<truncated>"
        logger.debug("%s %s", prefix, safe)

    def handle_message(self, message: str) -> Optional[str]:
        """
        Given a Discord message, returns a reply string if any [[...]] triggers are found.
        If nothing to reply with, returns None.
        """
        self._log_sanitized("Incoming message:", message)

        tokens = self.extract_triggers(message)
        logger.debug("Extracted tokens: %s", tokens)

        if not tokens:
            logger.debug("No tokens found; skipping reply")
            return None

        # Preserve order but avoid duplicate lookups for identical tokens in the same message
        seen = set()
        results: List[str] = []

        for tok in tokens:
            key = tok.upper()
            if key in seen:
                logger.debug("Skipping duplicate token: %r", tok)
                continue
            seen.add(key)
            card = self._lookup(tok)
            if card:
                logger.debug("Resolved token %r -> card '%s'", tok, card.name)
                results.append(_format_card_for_discord(card))
            else:
                logger.debug("No match for token: %r", tok)

        if not results:
            logger.debug("No cards resolved; skipping reply")
            return None

        body = "\n\n".join(results)
        footer = f"\n\n{self.reply_footer}" if self.reply_footer else ""
        reply = f"{body}{footer}"
        self._log_sanitized("Composed reply:", reply)
        return reply


# Example CLI usage (optional):
# python -m discord_alias_responder "I like [[Pets]] and [[Space Elevator]]"
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python discord_alias_responder.py <cards_csv_path> <message>")
        sys.exit(1)
    responder = DiscordAliasResponder.from_csv(sys.argv[1], reply_footer="")
    reply = responder.handle_message(" ".join(sys.argv[2:]))
    print(reply or "")
