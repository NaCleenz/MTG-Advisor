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
EDHRec top cards include: {top_cards}

I want to find HIDDEN GEM cards — powerful synergistic cards that aren't commonly recommended on EDHRec for this commander.

Think about:
- Unusual combinations with the commander's abilities
- Overlooked cards from older sets
- Cards that support the strategy but are underplayed

Return ONLY a valid JSON object (no markdown, no explanation) in this format:
{{
  "archetype_themes": ["theme1", "theme2"],
  "hidden_gem_queries": ["oracle text phrase 1", "oracle text phrase 2", "oracle text phrase 3", "oracle text phrase 4"],
  "card_types_to_search": ["Artifact", "Enchantment", "etc"]
}}

hidden_gem_queries should be 4-6 specific oracle text phrases that appear on underplayed but synergistic cards."""


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


async def analyze_archetype(commander: str, colors: str, top_card_names: list[str]) -> dict:
    sample = ", ".join(top_card_names[:20])
    prompt = _ARCHETYPE_PROMPT.format(
        commander=commander, colors=colors or "Colorless", top_cards=sample
    )
    raw    = await _chat(prompt)
    result = _extract_json(raw) if raw else None

    if result:
        return {
            "themes":     result.get("archetype_themes", []),
            "queries":    result.get("hidden_gem_queries", []),
            "card_types": result.get("card_types_to_search", []),
        }

    return {"themes": [], "queries": [], "card_types": []}


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
