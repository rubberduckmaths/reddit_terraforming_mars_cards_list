from dataclasses import dataclass
from typing import Dict, Iterable, Optional, List

from card_data_model import Card


def _norm_alias(s: str) -> str:
    """
    Normalize alias for case-insensitive lookup.
    """
    return " ".join(s.strip().split()).upper()


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
                    prev[j] + 1,        # deletion
                    curr[j - 1] + 1,    # insertion
                    prev[j - 1] + cost  # substitution
                )
            )
        prev = curr
    return prev[-1]


@dataclass
class CardIndex:
    by_alias: Dict[str, Card]
    by_name: Dict[str, Card]

    @classmethod
    def build(cls, cards: Iterable[Card]) -> "CardIndex":
        alias_map: Dict[str, Card] = {}
        name_map: Dict[str, Card] = {}
        for c in cards:
            name_key = _norm_alias(c.name)
            name_map[name_key] = c
            for alias in c.aliases:
                key = _norm_alias(alias)
                alias_map.setdefault(key, c)
            # also allow exact name lookups via alias map
            alias_map.setdefault(name_key, c)
        return cls(by_alias=alias_map, by_name=name_map)

    def lookup(self, token: str) -> Optional[Card]:
        """
        Lookup by Levenshtein distance to aliases/names.

        Strategy:
        - Exact match returns immediately.
        - Otherwise, compute Levenshtein distance between the normalized
          query and every alias/name key.
        - Pick the key with the smallest distance.
        - Accept only if the distance is within a reasonable threshold
          (max(2, len(query)//3)) to avoid wild mismatches.
        """
        if not token:
            return None
        norm_tok = _norm_alias(token)

        # Exact match
        exact = self.by_alias.get(norm_tok)
        if exact:
            return exact

        best_key: Optional[str] = None
        best_dist = 10**9

        for key in self.by_alias.keys():
            d = _levenshtein(norm_tok, key)
            if d < best_dist or (d == best_dist and len(key) > len(best_key or "")):
                best_dist = d
                best_key = key

        if best_key is None:
            return None

        # Guardrail: require “close enough” distance
        max_allowed = max(2, len(norm_tok) // 3)
        if best_dist <= max_allowed:
            return self.by_alias.get(best_key)

        return None
