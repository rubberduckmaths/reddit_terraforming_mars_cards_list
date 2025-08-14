# Python
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
        """
        Primary: extract [[token]] sequences.
        Fallback (if none found): treat the whole message as a short list of tokens
        separated by commas/pipes/newlines (e.g., 'Livestock, Steak').
        """
        raw = message or ""
        # Primary: [[...]] triggers
        tokens = [m.group(1).strip() for m in TRIGGER_RE.finditer(raw) if m.group(1).strip()]
        if tokens:
            logger.debug("extract_triggers: bracketed tokens=%r", tokens)
            return tokens

        # Fallback: parse simple lists only if the message looks like a token list
        fb = DiscordAliasResponder._extract_fallback_token_list(raw)
        logger.debug("extract_triggers: fallback tokens=%r", fb)
        return fb

    @staticmethod
    def _extract_fallback_token_list(raw: str) -> List[str]:
        """
        Heuristic fallback for messages that look like a short list of tokens.
        Keeps it conservative to avoid triggering in normal sentences.
        Rules:
        - Split by comma, pipe, slash or newline
        - Accept between 1 and 8 items
        - Each item trimmed; 1..60 chars
        - Drop items that look like URLs
        - If the message contains typical sentence punctuation and no separators,
          treat it as not-a-list and return []
        """
        text = (raw or "").strip()
        if not text:
            logger.debug("fallback: empty message")
            return []

        # If it already contains brackets, don’t double-parse here.
        if "[[" in text and "]]" in text:
            logger.debug("fallback: found bracket markers; skipping fallback")
            return []

        # If there are no obvious list separators and the text looks like a sentence, abort
        has_separators = any(sep in text for sep in (",", "|", "/", "\n"))
        looks_like_sentence = bool(re.search(r"[.!?]\s|^\w+\s+\w+\s+\w+", text))
        if not has_separators and looks_like_sentence:
            logger.debug("fallback: text looks like sentence without separators; skipping")
            return []

        parts = [p.strip() for p in re.split(r"[,\|/\n]+", text) if p.strip()]
        logger.debug("fallback: split parts(raw)=%r", parts)

        if not (1 <= len(parts) <= 8):
            logger.debug("fallback: parts count out of range (%d); skipping", len(parts))
            return []

        cleaned: List[str] = []
        for p in parts:
            if "http://" in p or "https://" in p:
                logger.debug("fallback: dropping URL-like part: %r", p)
                continue
            if not (1 <= len(p) <= 60):
                logger.debug("fallback: dropping due to length (%d): %r", len(p), p)
                continue
            cleaned.append(p)

        logger.debug("fallback: cleaned=%r", cleaned)
        return cleaned

    @staticmethod
    def _log_sanitized(prefix: str, text: str) -> None:
        if text is None:
            logger.debug("%s <none>", prefix)
            return
        safe = text.replace("@", "@\u200b").replace("\n", "\\n")
        if len(safe) > 300:
            safe = safe[:300] + "...<truncated>"
        logger.debug("%s %s", prefix, safe)

    def handle_message(self, message: str) -> Optional[str]:
        """
        Given a Discord message, returns a reply string if any triggers are found.
        Triggers: [[...]] or, if none, a conservative fallback list like 'A, B, C'.
        """
        self._log_sanitized("Incoming message:", message)

        tokens = self.extract_triggers(message)
        logger.debug("Extracted tokens: %s", tokens)

        if not tokens:
            logger.debug("No tokens found; skipping reply")
            return None

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
