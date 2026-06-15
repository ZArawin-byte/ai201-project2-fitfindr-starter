"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

MODEL = "llama-3.3-70b-versatile"

# Words that carry no signal for relevance scoring.
_STOPWORDS = {
    "a", "an", "the", "for", "with", "in", "of", "and", "or", "to", "my",
    "i", "im", "looking", "want", "need", "some", "something", "size",
    "under", "over", "that", "this", "it", "is", "are", "vibe", "vibes",
    "good", "nice", "cute", "really", "kind", "find", "thrift", "thrifted",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _tokenize(text: str) -> list[str]:
    """Lowercase a string and split it into alphanumeric word tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    listings = load_listings()

    # Normalize the query terms once.
    query_tokens = {t for t in _tokenize(description or "") if t not in _STOPWORDS}
    size_norm = size.strip().lower() if size else None

    scored: list[tuple[int, dict]] = []
    for item in listings:
        # ── Hard filters ──────────────────────────────────────────────
        if max_price is not None and item["price"] > max_price:
            continue
        if size_norm:
            item_size = item.get("size", "").lower()
            # Treat one-size / oversized items as matching any size request.
            flexible = "one size" in item_size or "oversized" in item_size
            if not flexible and size_norm not in item_size:
                continue

        # ── Relevance scoring (keyword overlap) ───────────────────────
        haystack_tokens = set()
        haystack_tokens.update(_tokenize(item["title"]))
        haystack_tokens.update(_tokenize(item["description"]))
        haystack_tokens.update(_tokenize(item["category"]))
        for tag in item.get("style_tags", []):
            haystack_tokens.update(_tokenize(tag))
        for color in item.get("colors", []):
            haystack_tokens.update(_tokenize(color))
        if item.get("brand"):
            haystack_tokens.update(_tokenize(item["brand"]))

        score = len(query_tokens & haystack_tokens)
        if score > 0:
            scored.append((score, item))

    # Highest score first; preserve dataset order for ties (stable sort).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handled gracefully.

    Returns:
        A non-empty string with outfit suggestions. If the wardrobe is empty,
        returns general styling advice for the item rather than raising or
        returning an empty string.
    """
    item_desc = (
        f"{new_item.get('title', 'this item')} "
        f"(category: {new_item.get('category', 'unknown')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []

    if not items:
        # Empty-wardrobe fallback: general styling advice, no named pieces.
        prompt = (
            f"A user is considering thrifting this piece: {item_desc}.\n"
            "They have not entered any wardrobe yet, so you don't know what they own.\n"
            "Suggest 1–2 complete outfit ideas built around this piece using GENERAL "
            "wardrobe staples (e.g. 'a pair of straight-leg jeans', 'white sneakers'). "
            "Describe the overall vibe and give one concrete styling tip. "
            "Keep it to 3–4 sentences, friendly and practical."
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it['name']} ({it.get('category', '')}; "
            f"colors: {', '.join(it.get('colors', []))}; "
            f"style: {', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            f"A user is considering thrifting this piece: {item_desc}.\n\n"
            f"Here is their current wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1–2 complete outfit combinations that pair the new piece with "
            "SPECIFIC, NAMED items from their wardrobe above. Reference the wardrobe "
            "pieces by name. Describe the vibe and give one concrete styling tip "
            "(tuck, roll, layer, etc.). Keep it to 3–4 sentences."
        )

    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a sharp, encouraging personal stylist who "
                    "gives specific, wearable outfit advice.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        text = resp.choices[0].message.content
        if text and text.strip():
            return text.strip()
        # LLM returned nothing usable — degrade gracefully.
        return (
            f"You could build a look around the {new_item.get('title', 'piece')} "
            "with simple staples like well-fitting jeans and clean sneakers — "
            "let the piece be the focal point."
        )
    except Exception as exc:
        # Never crash the agent on an API/network failure.
        return (
            f"Couldn't generate a full styling suggestion right now ({exc}). "
            f"As a starting point, the {new_item.get('title', 'piece')} pairs well "
            "with neutral basics — try it with simple bottoms and shoes you already own."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence caption usable as an Instagram/TikTok post. If outfit is
        empty or missing, returns a descriptive error message string — does NOT
        raise an exception.
    """
    # Guard against an empty / whitespace-only outfit input.
    if not outfit or not outfit.strip():
        return (
            "⚠️ Can't write a fit card yet — no outfit suggestion was provided. "
            "Generate an outfit first, then come back for the caption."
        )

    title = new_item.get("title", "this piece")
    price = new_item.get("price")
    platform = new_item.get("platform", "a thrift app")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"

    prompt = (
        f"Write a short, shareable social-media caption (an 'OOTD' / outfit post) "
        f"for a thrifted find.\n\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit it's styled in: {outfit}\n\n"
        "Rules:\n"
        "- Casual, authentic first-person voice (NOT a product description).\n"
        f"- Naturally mention the item, the price ({price_str}), and the platform "
        f"({platform}) once each.\n"
        "- Capture the outfit's vibe in specific terms.\n"
        "- 2–4 short sentences. A couple of emojis are fine. No hashtag spam."
    )

    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You write punchy, authentic-sounding thrift-haul "
                    "captions for social media.",
                },
                {"role": "user", "content": prompt},
            ],
            # Higher temperature → varied captions for the same input.
            temperature=1.0,
        )
        text = resp.choices[0].message.content
        if text and text.strip():
            return text.strip()
        return (
            f"thrifted this {title.lower()} for {price_str} off {platform} "
            "and it's already my favorite ✨"
        )
    except Exception as exc:
        return (
            f"⚠️ Couldn't generate a fit card right now ({exc}). "
            f"Here's a fallback: snagged this {title.lower()} for {price_str} "
            f"on {platform} 🛍️"
        )
