import httpx
from deck_parser import commander_to_slug

EDHREC_JSON = "https://json.edhrec.com/pages/commanders"

HEADERS = {
    "User-Agent": "MTGCommanderAdvisor/1.0 (personal deck tool)",
    "Accept": "application/json",
}


async def get_edhrec_recommendations(commander_name: str) -> dict:
    """
    Fetch EDHRec card recommendations for a commander.

    Returns:
      {
        "top_cards":        [{"name": str, "num_decks": int, "synergy": float}, ...],
        "high_synergy":     [...],
        "new_cards":        [...],
        "all_names":        set[str],  # lowercase names of all edhrec cards
        "themes":           [str],
        "edhrec_url":       str,
      }
    """
    slug = commander_to_slug(commander_name)
    url = f"{EDHREC_JSON}/{slug}.json"
    edhrec_url = f"https://edhrec.com/commanders/{slug}"

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        try:
            resp = await client.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return _empty_result(edhrec_url, str(e))

    return _parse_edhrec(data, edhrec_url)


def _parse_edhrec(data: dict, edhrec_url: str) -> dict:
    top_cards = []
    high_synergy = []
    new_cards = []
    themes = []
    all_names: set[str] = set()

    try:
        container = data.get("container", {})
        json_dict = container.get("json_dict", {})

        # Extract themes
        header_tags = json_dict.get("header_tags", [])
        themes = [t.get("label", "") for t in header_tags if t.get("label")]

        card_lists = json_dict.get("cardlists", [])

        for section in card_lists:
            tag = section.get("tag", "")
            card_views = section.get("cardviews", [])

            parsed = []
            for cv in card_views:
                name = cv.get("name", "")
                if not name:
                    continue
                entry = {
                    "name": name,
                    "num_decks": cv.get("num_decks", 0),
                    "synergy": cv.get("synergy", 0.0),
                    "url": f"https://edhrec.com{cv.get('url', '')}",
                }
                parsed.append(entry)
                all_names.add(name.lower())

            if "topcards" in tag or "top" in tag:
                top_cards = parsed
            elif "highsynergy" in tag or "synergy" in tag:
                high_synergy = parsed
            elif "newcard" in tag or "new" in tag:
                new_cards = parsed

    except Exception:
        pass

    return {
        "top_cards": top_cards[:50],
        "high_synergy": high_synergy[:30],
        "new_cards": new_cards[:20],
        "all_names": all_names,
        "themes": themes,
        "edhrec_url": edhrec_url,
    }


def _empty_result(edhrec_url: str, error: str = "") -> dict:
    return {
        "top_cards": [],
        "high_synergy": [],
        "new_cards": [],
        "all_names": set(),
        "themes": [],
        "edhrec_url": edhrec_url,
        "error": error,
    }
