import asyncio
import httpx
from typing import Optional

from deck_parser import parse_deck_list
from scryfall import (
    get_card_by_name,
    get_cards_by_name_list,
    search_cards,
    get_card_image,
    build_color_query,
    build_oracle_query,
)
from edhrec import get_edhrec_recommendations
from ollama_client import (
    is_ollama_available,
    analyze_problem,
    analyze_archetype,
    _theme_to_oracle_queries,
)


def _dedupe(cards: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for c in cards:
        name = c["name"].lower()
        if name not in seen:
            seen.add(name)
            out.append(c)
    return out


def _filter_deck(cards: list[dict], deck_set: set[str]) -> list[dict]:
    return [c for c in cards if c["name"].lower() not in deck_set]


def _categorize_by_price(cards: list[dict]) -> dict:
    buckets = {"budget": [], "mid": [], "premium": [], "luxury": [], "unknown": []}
    for c in cards:
        tier = c.get("price_tier", "unknown")
        buckets.setdefault(tier, []).append(c)
    return buckets


async def get_recommendations(
    deck_list: str,
    problem_statement: Optional[str],
    commander_override: Optional[str] = None,
) -> dict:
    # ── 1. Parse deck ────────────────────────────────────────────────────
    commander_name, deck_cards = parse_deck_list(deck_list)

    if commander_override:
        commander_name = commander_override
        # Remove the commander from the card list if the user accidentally included it
        deck_cards = [c for c in deck_cards if c.lower() != commander_name.lower()]

    if not commander_name:
        return {"error": "Could not identify a commander. Enter your commander in the Commander field above, or mark it in the deck list with *CMDR* or a 'Commander' section header."}

    deck_set = {c.lower() for c in deck_cards}
    deck_set.add(commander_name.lower())

    async with httpx.AsyncClient() as client:
        # ── 2. Fetch commander card from Scryfall ─────────────────────────
        commander_card = await get_card_by_name(commander_name, client)
        if not commander_card:
            return {"error": f"Could not find commander '{commander_name}' on Scryfall. Check spelling."}

        color_identity: list[str] = commander_card.get("color_identity", [])
        color_str = "".join(color_identity) if color_identity else "C"

        # ── 3. Fetch EDHRec data ──────────────────────────────────────────
        edhrec_data = await get_edhrec_recommendations(commander_name)
        edhrec_names: set[str] = edhrec_data["all_names"]

        # ── 4. Ollama problem analysis (if provided) ──────────────────────
        ollama_ok = await is_ollama_available()
        analysis_text = ""
        oracle_keywords: list[str] = []
        card_types: list[str] = []

        if problem_statement:
            if ollama_ok:
                result = await analyze_problem(problem_statement, commander_name, color_str)
                analysis_text = result.get("analysis", "")
                oracle_keywords = result.get("search_terms", [])
                card_types = result.get("card_types", [])
            else:
                from ollama_client import _naive_keywords
                oracle_keywords = _naive_keywords(problem_statement)
                analysis_text = "AI unavailable — using basic keyword matching. Add a GROQ_API_KEY for full analysis."

        # ── 5. Build main recommendations ────────────────────────────────
        recommendations: list[dict] = []

        if oracle_keywords:
            # Problem-based: search Scryfall for oracle text matches
            color_q = build_color_query(color_identity)
            oracle_q = build_oracle_query(oracle_keywords)
            query = f"{color_q} {oracle_q} format:commander -is:land"
            found = await search_cards(query, client, max_cards=60)
            found = _filter_deck(found, deck_set)
            recommendations = _dedupe(found)
        else:
            # No problem: use EDHRec top + high synergy cards enriched with images
            all_edhrec = (
                edhrec_data["top_cards"][:40]
                + edhrec_data["high_synergy"][:20]
            )
            names_to_fetch = [c["name"] for c in all_edhrec if c["name"].lower() not in deck_set]
            enriched = await get_cards_by_name_list(names_to_fetch, client)

            for e_card in all_edhrec:
                name_lower = e_card["name"].lower()
                if name_lower in deck_set:
                    continue
                card_data = enriched.get(name_lower)
                if card_data:
                    card_data["synergy"] = e_card.get("synergy", 0)
                    recommendations.append(card_data)

        # ── 6. Hidden Gems ────────────────────────────────────────────────
        hidden_gems: list[dict] = []
        edhrec_themes = edhrec_data.get("themes", [])

        if ollama_ok:
            top_names = [c["name"] for c in edhrec_data["top_cards"][:20]]
            archetype = await analyze_archetype(
                commander_name, color_str, top_names, edhrec_themes
            )
            gem_queries = archetype.get("queries", [])
        else:
            # Fallback: map EDHRec archetype themes to oracle text phrases
            gem_queries = _theme_to_oracle_queries(edhrec_themes)
            if not gem_queries:
                gem_queries = _default_gem_queries(color_identity, edhrec_themes)

        if gem_queries:
            color_q = build_color_query(color_identity)
            oracle_q = build_oracle_query(gem_queries[:5])
            gem_query = f"{color_q} {oracle_q} format:commander -is:land"
            gem_results = await search_cards(gem_query, client, max_cards=80)

            for card in gem_results:
                name_lower = card["name"].lower()
                if name_lower in deck_set:
                    continue
                if name_lower in edhrec_names:
                    continue  # Must NOT be on EDHRec
                hidden_gems.append(card)
                if len(hidden_gems) >= 30:
                    break

            hidden_gems = _dedupe(hidden_gems)

        # ── 7. Assemble response ──────────────────────────────────────────
        categorized = _categorize_by_price(recommendations)
        hidden_categorized = _categorize_by_price(hidden_gems)

        return {
            "commander": {
                "name": commander_name,
                "image_url": get_card_image(commander_card),
                "color_identity": color_identity,
                "type_line": commander_card.get("type_line", ""),
                "oracle_text": commander_card.get("oracle_text", ""),
                "scryfall_uri": commander_card.get("scryfall_uri", ""),
            },
            "problem_analysis": analysis_text,
            "oracle_keywords": oracle_keywords,
            "card_types": card_types,
            "ai_available": ollama_ok,
            "recommendations": categorized,
            "hidden_gems": hidden_categorized,
            "edhrec_url": edhrec_data.get("edhrec_url", ""),
            "deck_size": len(deck_cards),
        }


def _default_gem_queries(color_identity: list[str], themes: list[str]) -> list[str]:
    """Fallback Hidden Gem queries when Ollama is unavailable."""
    queries = []
    colors = set(c.upper() for c in color_identity)

    if "G" in colors:
        queries += ["proliferate", "counters on it", "search your library for a Forest"]
    if "U" in colors:
        queries += ["scry 2", "whenever you draw", "flash"]
    if "B" in colors:
        queries += ["sacrifice a creature", "return target creature card", "loses life"]
    if "R" in colors:
        queries += ["whenever you cast", "haste", "deals combat damage"]
    if "W" in colors:
        queries += ["vigilance", "whenever a creature", "exile target"]

    return queries[:5] if queries else ["enters the battlefield", "each opponent", "draw a card"]
