import re
from typing import Optional


def parse_deck_list(deck_list: str) -> tuple[Optional[str], list[str]]:
    """
    Parse a MTG deck list in multiple common formats.
    Returns (commander_name, [card_names])

    Supported formats:
      - Moxfield/Archidekt: "Commander\\n1 Name\\n\\nDeck\\n1 Card..."
      - MTGO tag:           "1 Name *CMDR*"
      - Inline tag:         "1 Name (CMDR)"
      - Header:             "Commander: Name"
      - Plain (first card): fallback — first 1-of legendary assumed commander
    """
    lines = deck_list.strip().splitlines()
    commander: Optional[str] = None
    cards: list[str] = []
    section = "deck"  # current section: "commander" | "deck" | "skip"

    for raw in lines:
        line = raw.strip()

        if not line or line.startswith("//") or line.startswith("#"):
            continue

        lower = line.lower()

        # ── Section headers ──────────────────────────────────────────────
        if lower == "commander":
            section = "commander"
            continue
        if lower in ("deck", "mainboard", "main", "maindeck"):
            section = "deck"
            continue
        if lower in ("sideboard", "maybeboard", "companion", "tokens", "considering"):
            section = "skip"
            continue

        # ── "Commander: Name" header style ───────────────────────────────
        if lower.startswith("commander:"):
            candidate = line.split(":", 1)[1].strip()
            candidate = _clean_name(candidate)
            if candidate:
                commander = candidate
            continue

        if section == "skip":
            continue

        # ── Standard card line: "1 Name" / "1x Name" ────────────────────
        match = re.match(r"^(\d+)[xX]?\s+(.+)$", line)
        if not match:
            continue

        quantity = int(match.group(1))
        raw_name = match.group(2).strip()

        # Detect inline commander markers
        is_cmdr = bool(
            re.search(r"\*CMDR\*|\*Commander\*|\(CMDR\)|\[CMDR\]", raw_name, re.IGNORECASE)
        )

        # Strip set/collector/foil/commander annotations
        card_name = re.sub(r"\s*[\(\[]\s*[A-Z0-9]{2,6}\s*[\)\]]", "", raw_name)  # (SET)
        card_name = re.sub(r"\s*\d+\s*$", "", card_name)                            # trailing number
        card_name = re.sub(r"\s*\*CMDR\*|\s*\*Commander\*|\s*\(CMDR\)|\s*\[CMDR\]", "", card_name, flags=re.IGNORECASE)
        card_name = card_name.strip()

        if not card_name:
            continue

        if is_cmdr or section == "commander":
            commander = card_name
            section = "deck"  # next lines go to deck
        else:
            cards.append(card_name)

    return commander, cards


def _clean_name(name: str) -> str:
    name = re.sub(r"\s*[\(\[]\s*[A-Z0-9]{2,6}\s*[\)\]]", "", name)
    name = re.sub(r"\s*\d+\s*$", "", name)
    return name.strip()


def commander_to_slug(name: str) -> str:
    """Convert a commander name to the EDHRec URL slug."""
    slug = name.lower()
    # Remove apostrophes/quotes entirely
    slug = re.sub(r"[''`\"']", "", slug)
    # Replace commas, slashes, and other punctuation with spaces
    slug = re.sub(r"[,./\\|]", " ", slug)
    # Collapse whitespace → hyphens
    slug = re.sub(r"\s+", "-", slug.strip())
    # Remove remaining non-alphanumeric-hyphen chars
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Collapse repeated hyphens
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")
