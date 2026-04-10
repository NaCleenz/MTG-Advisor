"""
AI client — uses Groq (free tier) with graceful fallback to keyword matching.
Set GROQ_API_KEY as an environment variable (Railway dashboard or local .env).
"""

import json
import os
from typing import Optional

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_PROBLEM_PROMPT = """You are an expert Magic: The Gathering EDH/Commander deck builder.

A player has this problem with their commander deck:
"{problem}"

Their commander is: {commander}
Commander colors: {colors}

Analyze the problem and identify what oracle text phrases on MTG cards would solve it.
Be specific — think about actual text that appears on cards.

Return ONLY a valid JSON object (no markdown, no explanation) in this exact format:
{{
  "analysis": "One paragraph explaining what kinds of cards would help and why",
  "search_terms": ["phrase1", "phrase2", "phrase3"],
  "card_types": ["Ramp", "Card Draw", "etc"]
}}

search_terms should be 4-8 short oracle text phrases like "search your library for a basic land", "draw a card", "counter target spell", etc."""

_ARCHETYPE_PROMPT = """You are an expert Magic: The Gathering EDH/Commander historian.

Commander: {commander}
Colors: {colors}
Primary EDHRec archetype themes: {themes}
EDHRec top cards include: {top_cards}

I want to find HIDDEN GEM cards — powerful synergistic cards that aren't commonly recommended on EDHRec for this commander.
The commander's primary archetype is based on the EDHRec themes listed above. Focus on that archetype.

Think about:
- Unusual oracle text phrases that synergize with the archetype
- Overlooked cards from older sets that support the strategy
- Cards that enable the archetype's win condition in unexpected ways

Return ONLY a valid JSON object (no markdown, no explanation) in this format:
{{
  "archetype_themes": ["theme1", "theme2"],
  "hidden_gem_queries": ["oracle text phrase 1", "oracle text phrase 2", "oracle text phrase 3", "oracle text phrase 4"],
  "card_types_to_search": ["Artifact", "Enchantment", "etc"]
}}

hidden_gem_queries should be 4-6 specific oracle text phrases (as they appear on real MTG cards) that find underplayed but synergistic cards for the archetype."""


def is_ai_available() -> bool:
    """Return True if a Groq API key is configured."""
    return bool(GROQ_API_KEY)


# Keep old name as alias so recommender.py works without changes
async def is_ollama_available() -> bool:
    return is_ai_available()


async def _chat(prompt: str) -> Optional[str]:
    """Call Groq chat completions API."""
    if not GROQ_API_KEY:
        return None

    # Import here so the app still starts if groq isn't installed yet
    try:
        from groq import AsyncGroq
    except ImportError:
        print("[AI] groq package not installed. Run: pip install groq")
        return None

    try:
        client = AsyncGroq(api_key=GROQ_API_KEY)
        completion = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800,
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"[AI] Groq error: {e}")
        return None


def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON from LLM response, tolerating markdown fences."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


async def analyze_problem(problem: str, commander: str, colors: str) -> dict:
    prompt = _PROBLEM_PROMPT.format(
        problem=problem, commander=commander, colors=colors or "Colorless"
    )
    raw    = await _chat(prompt)
    result = _extract_json(raw) if raw else None

    if result:
        return {
            "analysis":     result.get("analysis", ""),
            "search_terms": result.get("search_terms", []),
            "card_types":   result.get("card_types", []),
        }

    return {
        "analysis":     "",
        "search_terms": _naive_keywords(problem),
        "card_types":   [],
    }


async def analyze_archetype(
    commander: str,
    colors: str,
    top_card_names: list[str],
    edhrec_themes: list[str] | None = None,
) -> dict:
    sample        = ", ".join(top_card_names[:20])
    themes_str    = ", ".join(edhrec_themes[:5]) if edhrec_themes else "unknown"
    prompt = _ARCHETYPE_PROMPT.format(
        commander=commander,
        colors=colors or "Colorless",
        themes=themes_str,
        top_cards=sample,
    )
    raw    = await _chat(prompt)
    result = _extract_json(raw) if raw else None

    if result:
        return {
            "themes":     result.get("archetype_themes", []),
            "queries":    result.get("hidden_gem_queries", []),
            "card_types": result.get("card_types_to_search", []),
        }

    # AI call failed — fall back to theme-based oracle queries
    fallback = _theme_to_oracle_queries(edhrec_themes or [])
    return {"themes": edhrec_themes or [], "queries": fallback, "card_types": []}


# Maps EDHRec archetype/theme labels → oracle text phrases for Scryfall searches.
# Phrases are chosen to appear verbatim on real MTG cards.
_THEME_ORACLE_MAP: dict[str, list[str]] = {
    # +1/+1 counters / proliferate
    "counters":      ["+1/+1 counter", "proliferate", "counter on it"],
    "proliferate":   ["proliferate", "+1/+1 counter", "poison counter"],
    "infect":        ["infect", "poison counter", "proliferate"],
    # Tokens / go-wide
    "tokens":        ["create a", "token", "populate"],
    "go-wide":       ["create a", "token", "creatures you control get"],
    # Graveyard / recursion
    "reanimator":    ["return target creature card from your graveyard", "put onto the battlefield from your graveyard"],
    "graveyard":     ["from your graveyard", "return target creature card", "cards from their library into their graveyard"],
    "self-mill":     ["mill", "put the top", "from your library into your graveyard"],
    # Sacrifice / aristocrats
    "sacrifice":     ["sacrifice a creature", "whenever a creature dies", "sacrifice another"],
    "aristocrats":   ["whenever a creature dies", "sacrifice a creature", "each opponent loses"],
    # Equipment / voltron
    "voltron":       ["equipped creature gets", "attach", "aura attached to"],
    "equipment":     ["equip", "equipped creature", "whenever equipped creature"],
    "auras":         ["enchanted creature gets", "aura you control", "whenever an aura"],
    # Enchantress
    "enchantress":   ["whenever you cast an enchantment", "enchantment enters", "whenever an enchantment"],
    # Spells / storm
    "spellslinger":  ["whenever you cast an instant or sorcery", "copy of that spell", "storm"],
    "storm":         ["storm", "whenever you cast a spell", "copy of that spell"],
    "spells":        ["whenever you cast", "copy target", "magecraft"],
    # Blink / ETB
    "blink":         ["exile target creature you control", "return it to the battlefield", "enters the battlefield under your control"],
    "flicker":       ["exile target creature you control", "return it to the battlefield"],
    "etb":           ["whenever ~ enters", "enters the battlefield", "as ~ enters"],
    # Tribal
    "tribal":        ["creatures you control get", "other creatures of the chosen type", "whenever a creature"],
    "zombies":       ["zombie", "whenever a creature dies", "from your graveyard"],
    "elves":         ["elf", "add {G}", "whenever you tap"],
    "dragons":       ["dragon", "whenever a dragon", "flying"],
    "vampires":      ["vampire", "lifelink", "whenever a creature dies"],
    "goblins":       ["goblin", "sacrifice a goblin", "create a 1/1 red Goblin"],
    "merfolk":       ["merfolk", "islandwalk", "whenever you draw"],
    "humans":        ["human", "whenever a human", "creatures you control get"],
    "spirits":       ["spirit", "flash", "whenever a spirit"],
    "slivers":       ["sliver", "all slivers have", "slivers you control"],
    # Lifegain
    "lifegain":      ["you gain life", "whenever you gain life", "lifelink"],
    "life":          ["whenever you gain life", "you gain", "lifelink"],
    # Artifacts
    "artifacts":     ["whenever an artifact", "artifact you control", "treasure token"],
    "artifact":      ["whenever an artifact", "artifact enters", "create a Treasure token"],
    # Lands / landfall
    "lands":         ["landfall", "whenever a land enters", "search your library for a basic land"],
    "landfall":      ["landfall", "whenever a land enters the battlefield", "put a land"],
    # Mill
    "mill":          ["mill", "cards from the top of their library", "put into their graveyard from their library"],
    # Draw / card advantage
    "draw":          ["whenever you draw a card", "draw two cards", "draw a card at the beginning"],
    "card draw":     ["draw a card", "whenever you draw", "draw two cards"],
    # Control / permission
    "control":       ["counter target spell", "return target permanent", "exile target"],
    # Planeswalkers / superfriends
    "superfriends":  ["planeswalker you control", "loyalty counter", "whenever a loyalty"],
    "planeswalkers": ["planeswalker", "loyalty counter", "whenever a loyalty"],
    # Stax / tax
    "stax":          ["spells cost {1} more", "as an additional cost", "players can't"],
    "tax":           ["spells cost {1} more", "opponents can't", "whenever an opponent"],
    # Ramp
    "ramp":          ["search your library for a basic land", "add {G}{G}", "put it onto the battlefield tapped"],
    # Discard / madness
    "discard":       ["discard a card", "whenever you discard", "madness"],
    "madness":       ["madness", "discard a card", "whenever you discard"],
    # Burn / damage
    "burn":          ["deals damage", "damage to any target", "deals 1 damage"],
    "aggro":         ["haste", "trample", "first strike"],
}


def _theme_to_oracle_queries(themes: list[str]) -> list[str]:
    """Map EDHRec theme labels to Scryfall oracle text search phrases."""
    queries: list[str] = []
    seen: set[str] = set()
    for theme in themes:
        key = theme.lower().strip()
        for map_key, phrases in _THEME_ORACLE_MAP.items():
            if map_key in key or key in map_key:
                for p in phrases:
                    if p not in seen:
                        seen.add(p)
                        queries.append(p)
                break  # one match per theme is enough
    return queries[:6]


def _naive_keywords(problem: str) -> list[str]:
    """Basic keyword extraction used when AI is unavailable."""
    lower    = problem.lower()
    keywords = []
    if any(w in lower for w in ["mana", "ramp", "land", "curve"]):
        keywords += ["search your library for a basic land", "add {G}", "land"]
    if any(w in lower for w in ["draw", "card advantage", "hand"]):
        keywords += ["draw a card", "draw two cards"]
    if any(w in lower for w in ["removal", "destroy", "kill", "deal damage"]):
        keywords += ["destroy target", "exile target", "deals damage"]
    if any(w in lower for w in ["counter", "control", "stop"]):
        keywords += ["counter target spell", "counter target"]
    if any(w in lower for w in ["slow", "fast", "speed", "tempo"]):
        keywords += ["flash", "haste"]
    if any(w in lower for w in ["token", "wide", "swarm"]):
        keywords += ["create", "token"]
    if any(w in lower for w in ["big", "threat", "win", "finisher"]):
        keywords += ["trample", "indestructible"]
    return keywords or ["synergy"]
