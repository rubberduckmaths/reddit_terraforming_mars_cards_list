import csv
import logging
import json
from pathlib import Path
from typing import Iterable, List

from card_data_model import Card

# Enable DEBUG logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def _split_multi(value: str) -> List[str]:
    """
    Parse multi-value fields. Prefer JSON arrays (e.g., ["A","B"]) when present,
    otherwise fall back to splitting by comma/pipe.
    """
    if not value:
        return []

    s = value.strip()
    # Try to parse JSON-style arrays first
    if s.startswith("[") and s.endswith("]"):
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except Exception:
            logger.debug("Failed to parse JSON array from value: %r; falling back to split", value)

    # Fallback: split by comma/pipe
    parts: List[str] = []
    for chunk in value.replace("|", ",").split(","):
        token = chunk.strip().strip('"').strip("'").strip()
        # Also trim any stray leading/trailing brackets from non-JSON cases
        token = token.lstrip("[").rstrip("]")
        if token:
            parts.append(token)
    return parts


def load_cards_from_csv(csv_path: str | Path) -> List[Card]:
    path = Path(csv_path)
    logger.debug("Loading cards from CSV: %s", path)
    if not path.exists():
        logger.error("Cards CSV not found at %s", path)
        raise FileNotFoundError(f"Cards CSV not found: {path}")
    cards: List[Card] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"Name", "Cost", "Description", "Tags", "Aliases"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            logger.error("CSV missing required columns: %s", missing)
            raise ValueError(f"CSV missing required columns: {missing}")

        has_number = "Number" in (reader.fieldnames or [])

        for i, row in enumerate(reader, start=2):  # start=2 accounts for header line
            try:
                name = (row["Name"] or "").strip()
                cost = (row["Cost"] or "").strip()  # keep cost as string
                description = (row["Description"] or "").strip()
                tags = _split_multi(row.get("Tags", ""))
                aliases = _split_multi(row.get("Aliases", ""))
                number = (row["Number"].strip() if has_number and row.get("Number") is not None else None)

                if not name:
                    logger.debug("Skipping row %d: empty name", i)
                    continue
                tags = [t.strip() for t in tags if t.strip()]
                aliases = [a.strip() for a in aliases if a.strip()]
                cards.append(Card(
                    name=name,
                    cost=cost,
                    description=description,
                    tags=tags,
                    aliases=aliases,
                    number=number or None,
                ))
                logger.debug(
                    "Loaded card '%s' (cost=%s, tags=%d, aliases=%d%s) from row %d",
                    name,
                    cost,
                    len(tags),
                    len(aliases),
                    f', number="{number}"' if number else "",
                    i,
                )
            except Exception:
                logger.exception("Skipping malformed row %d due to parse error", i)
                continue
    logger.info("Loaded %d cards from %s", len(cards), path)
    return cards
