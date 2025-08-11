from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Card:
    name: str
    cost: str  # cost is a string in CSV
    description: str
    tags: List[str]
    aliases: List[str]
    number: Optional[str] = None  # optional: present if CSV has "Number"
