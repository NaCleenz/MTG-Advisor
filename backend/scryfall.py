import asyncio
import httpx
from typing import Optional

SCRYFALL_BASE = "https://api.scryfall.com"
# Scryfall requests a polite 50-100ms delay between calls
_REQUEST_DELAY = 0.1


def get_card_image(card: dict) -> Optional[str]:
    """Extract the best available image URL from a Scryfall card object."""
    if "image_uris" in card:
        return card["image_uris"].get("normal") or card["image_uris"].get("large")
    # Double-faced / modal cards
    faces = card.get("card_faces", [])
    if faces and "image_uris" in faces[0]:
        return faces[0]["image_uris"].get("normal") or faces[0]["image_uris"].get("large")
    return None


def card_price(card: dict) -> Optional[float]:
    """Return USD price as float, or None if unavailable."""
    prices = card.get("prices", {})
    usd = prices.get("usd") or prices.get("usd_foil")
    try:
        return float(usd) if usd else None
    except (TypeError, ValueError):
        return None


def price_tier(price: Optional[float]) -> str:
    if price is None:
        return "unknown"
    if price < 1:
        return "budget"
    if price < 5:
        return "mid"
    if price < 20:
        return "premium"
    return "luxury"


def _card_to_summary(card: dict) -> dict:
    price = card_price(card)
    return {
        "name": card.get("name", ""),
        "image_url": get_card_image(card),
        "price_usd": price,
        "price_tier": price_tier(price),
        "oracle_text": card.get("oracle_text") or (
            card.get("card_faces", [{}])[0].get("oracle_text", "")
        ),
        "type_line": card.get("type_line", ""),
        "cmc": card.get("cmc", 0),
        "color_identity": card.get("color_identity", []),
        "scryfall_uri": card.get("scryfall_uri", ""),
    }


async def get_card_by_name(name: str, client: httpx.AsyncClient) -> Optional[dict]:
    """Fetch a single card by exact name."""
    await asyncio.sleep(_REQUEST_DELAY)
    try:
        resp = await client.get(
            f"{SCRYFALL_BASE}/cards/named",
            params={"exact": name},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        # Try fuzzy search
        try:
            await asyncio.sleep(_REQUEST_DELAY)
            resp = await client.get(
                f"{SCRYFALL_BASE}/cards/named",
                params={"fuzzy": name},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None


async def search_cards(
    query: str,
    client: httpx.AsyncClient,
    max_cards: int = 30,
) -> list[dict]:
    """Search Scryfall and return up to max_cards card summaries."""
    results = []
    page = 1

    while len(results) < max_cards:
        await asyncio.sleep(_REQUEST_DELAY)
        try:
            resp = await client.get(
                f"{SCRYFALL_BASE}/cards/search",
                params={"q": query, "order": "edhrec", "page": page},
                timeout=15,
            )
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        for card in data.get("data", []):
            results.append(_card_to_summary(card))
            if len(results) >= max_cards:
                break

        if not data.get("has_more") or len(results) >= max_cards:
            break
        page += 1

    return results


async def get_cards_by_name_list(
    names: list[str], client: httpx.AsyncClient
) -> dict[str, dict]:
    """Fetch multiple cards by name, returns {name: card_summary}."""
    # Use Scryfall collection endpoint for efficiency (up to 75 at a time)
    results = {}
    chunk_size = 75

    for i in range(0, len(names), chunk_size):
        chunk = names[i : i + chunk_size]
        identifiers = [{"name": n} for n in chunk]
        await asyncio.sleep(_REQUEST_DELAY)
        try:
            resp = await client.post(
                f"{SCRYFALL_BASE}/cards/collection",
                json={"identifiers": identifiers},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            for card in data.get("data", []):
                results[card["name"].lower()] = _card_to_summary(card)
        except Exception:
            pass

    return results


def build_color_query(color_identity: list[str]) -> str:
    """Build a Scryfall color identity constraint."""
    if not color_identity:
        return "id:c"
    colors = "".join(color_identity)
    return f"id<={colors}"


def build_oracle_query(keywords: list[str]) -> str:
    """Build Scryfall oracle text OR query from keyword list."""
    if not keywords:
        return ""
    parts = [f'o:"{kw}"' for kw in keywords]
    return "(" + " OR ".join(parts) + ")"
