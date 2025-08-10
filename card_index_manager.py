from dataclasses import dataclass
from typing import Dict, Iterable, Optional, List

from card_data_model import Card


def _norm_alias(s: str) -> str:
    """
    Normalize alias for case-insensitive lookup.
    """
    return " ".join(s.strip().split()).upper()


def _common_prefix_len(a: str, b: str) -> int:
    """
    Length of the common prefix between a and b.
    """
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _levenshtein(a: str, b: str) -> int:
    """
    Compute Levenshtein edit distance between two strings (iterative DP).
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(
                min(
                    prev[j] + 1,      # deletion
                    curr[j - 1] + 1,  # insertion
                    prev[j - 1] + cost,  # substitution
                )
            )
        prev = curr
    return prev[-1]


def _split_words(key: str) -> List[str]:
    """
    Split a key into alpha-numeric words to compare against tokens.
    """
    # Keep simple: split on spaces and punctuation by replacing with space
    cleaned = []
    for ch in key:
        cleaned.append(ch if ch.isalnum() else " ")
    return [w for w in "".join(cleaned).split() if w]


@dataclass
class CardIndex:
    by_alias: Dict[str, Card]
    by_name: Dict[str, Card]

    @classmethod
    def build(cls, cards: Iterable[Card]) -> "CardIndex":
        alias_map: Dict[str, Card] = {}
        name_map: Dict[str, Card] = {}
        for c in cards:
            name_key = _norm_alias(c.name)  # reuse normalization
            name_map[name_key] = c
            for alias in c.aliases:
                key = _norm_alias(alias)
                # If collisions occur, prefer the first encountered
                alias_map.setdefault(key, c)
            # Also allow looking up by exact name as an alias
            alias_map.setdefault(name_key, c)
        return cls(by_alias=alias_map, by_name=name_map)

    def lookup(self, token: str) -> Optional[Card]:
        """
        Lookup by exact or nearest partial match against aliases and names.

        Strategy:
        - Exact match returns immediately.
        - Score each candidate key by:
          1) Longest common prefix with any word in the key (handles 'tharis' vs 'THARSIS REPUBLIC').
          2) Negative Levenshtein distance to the closest key word (smaller distance is better).
          3) Length of generic substring match (token in key or key in token).
          4) Key length (prefer more specific/longer keys in ties).
        - Pick the candidate with the highest score. Require at least a weak signal:
          prefix_len > 0 OR substring_len > 0 OR edit_distance <= 2.
        """
        if not token:
            return None
        norm_tok = _norm_alias(token)

        # Exact alias/name match
        exact = self.by_alias.get(norm_tok)
        if exact:
            return exact

        best_key = None
        best_score = (-1, -10_000, -1, -1)  # (prefix_len, -edit_dist, substr_len, key_len)

        for key in self.by_alias.keys():
            # Split into words for more human-like matching
            words = _split_words(key)

            # 1) Common prefix with any word
            prefix_len = 0
            for w in words:
                prefix_len = max(prefix_len, _common_prefix_len(norm_tok, w))

            # 2) Min edit distance to any word (and also consider whole key once)
            edit_dist = _levenshtein(norm_tok, key)
            for w in words:
                edit_dist = min(edit_dist, _levenshtein(norm_tok, w))

            # 3) Substring signal (legacy behavior)
            if norm_tok in key:
                substr_len = len(norm_tok)
            elif key in norm_tok:
                substr_len = len(key)
            else:
                substr_len = 0

            score = (prefix_len, -edit_dist, substr_len, len(key))
            if score > best_score:
                best_score = score
                best_key = key

        # Accept only if there is a reasonable signal
        if best_key:
            prefix_len, neg_edit, substr_len, _ = best_score
            if prefix_len > 0 or substr_len > 0 or (-neg_edit) <= 2:
                return self.by_alias.get(best_key)

        return None
