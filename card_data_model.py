from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Card:
    name: str
    cost: str  # cost is a string in CSV
    description: str
    tags: List[str]
    aliases: List[str]
