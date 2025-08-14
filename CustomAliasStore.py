# Python
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple


@dataclass(frozen=True)
class AliasEntry:
    name: str
    alias: str


class CustomAliasStore:
    """
    CSV schema:
    Name,Alias
    Colonizer Training Camp,CTC
    Asteroid Mining,Space Miner
    """
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._aliases_by_name: Dict[str, Set[str]] = {}
        self._seen_lower: Set[Tuple[str, str]] = set()  # (name_lower, alias_lower)

        # Ensure directory exists
        if self._path.parent and not self._path.parent.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)

        # Create file with header if missing
        if not self._path.exists():
            self._path.write_text("Name,Alias\n", encoding="utf-8", newline="")

        self._load_all()

    def _load_all(self) -> None:
        self._aliases_by_name.clear()
        self._seen_lower.clear()
        with self._path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("Name") or "").strip()
                alias = (row.get("Alias") or "").strip()
                if not name or not alias:
                    continue
                self._add_in_memory(name, alias)

    def _add_in_memory(self, name: str, alias: str) -> None:
        key = (name.casefold(), alias.casefold())
        if key in self._seen_lower:
            return
        self._seen_lower.add(key)
        self._aliases_by_name.setdefault(name, set()).add(alias)

    def add_alias(self, name: str, alias: str) -> bool:
        """
        Adds alias to memory and file (append-only, no rewrite).
        Returns True if new, False if it was already present (case-insensitive).
        """
        name_clean = name.strip()
        alias_clean = alias.strip()
        if not name_clean or not alias_clean:
            return False

        key = (name_clean.casefold(), alias_clean.casefold())
        if key in self._seen_lower:
            return False

        # Append to file
        with self._path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([name_clean, alias_clean])

        # Update memory
        self._add_in_memory(name_clean, alias_clean)
        return True

    def all_aliases(self) -> Dict[str, Set[str]]:
        return {k: set(v) for k, v in self._aliases_by_name.items()}

    def entries(self) -> List[AliasEntry]:
        out: List[AliasEntry] = []
        for name, aliases in self._aliases_by_name.items():
            for a in sorted(aliases):
                out.append(AliasEntry(name=name, alias=a))
        return out
