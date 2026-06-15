"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── query parsing ─────────────────────────────────────────────────────────────

# Recognized size tokens, longest first so "XXS" wins over "XS"/"S".
_SIZE_TOKENS = ["xxs", "xxl", "xs", "xl", "s", "m", "l"]


def parse_query(query: str) -> dict:
    """
    Extract structured search parameters from a free-text query.

    Returns a dict with:
        description (str): the query with price/size phrases stripped out,
                           used as keywords for search_listings.
        size (str | None): an explicit size if the user named one.
        max_price (float | None): a price ceiling if the user named one.

    Parsing is intentionally simple (regex, not an LLM call) so the loop is
    fast and deterministic. Anything it can't confidently extract is left None,
    which tells search_listings to skip that filter.
    """
    text = query.lower()

    # max_price: "under $30", "below 40", "less than $25", "$30"
    max_price = None
    price_match = re.search(
        r"(?:under|below|less than|max|<)\s*\$?\s*(\d+(?:\.\d+)?)", text
    )
    if not price_match:
        price_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", text)
    if price_match:
        max_price = float(price_match.group(1))

    # size: "size M", "size 8", or a standalone size token.
    size = None
    size_match = re.search(r"size\s+([a-z0-9]+)", text)
    if size_match:
        size = size_match.group(1).upper()
    else:
        for tok in _SIZE_TOKENS:
            if re.search(rf"\b{tok}\b", text):
                size = tok.upper()
                break

    # description: drop the price/size phrasing so they don't pollute keywords.
    description = re.sub(
        r"(?:under|below|less than|max|<)\s*\$?\s*\d+(?:\.\d+)?", " ", text
    )
    description = re.sub(r"\$\s*\d+(?:\.\d+)?", " ", description)
    description = re.sub(r"size\s+[a-z0-9]+", " ", description)
    description = re.sub(r"\s+", " ", description).strip()

    return {"description": description or query, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1 — initialize session state.
    session = _new_session(query, wardrobe)

    # Guard: empty query. Nothing to plan around.
    if not query or not query.strip():
        session["error"] = (
            "Please describe what you're looking for — e.g. "
            "'vintage graphic tee under $30, size M'."
        )
        return session

    # Step 2 — parse the query into structured search parameters.
    session["parsed"] = parse_query(query)
    parsed = session["parsed"]

    # Step 3 — TOOL CALL #1: search_listings.
    session["search_results"] = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )

    # BRANCH: no results → set a helpful error and STOP. Do not call the
    # downstream tools with empty input.
    if not session["search_results"]:
        hints = []
        if parsed["max_price"] is not None:
            hints.append(f"raising your ${parsed['max_price']:.0f} budget")
        if parsed["size"]:
            hints.append(f"removing the size {parsed['size']} filter")
        hints.append("trying broader keywords")
        session["error"] = (
            f"No listings matched \"{query}\". Try {', or '.join(hints)}."
        )
        return session

    # Step 4 — select the top (most relevant) result and store it in state.
    session["selected_item"] = session["search_results"][0]

    # Step 5 — TOOL CALL #2: suggest_outfit, using the item we just found and
    # the wardrobe. State flows in: selected_item came from step 4.
    session["outfit_suggestion"] = suggest_outfit(
        new_item=session["selected_item"],
        wardrobe=session["wardrobe"],
    )

    # Step 6 — TOOL CALL #3: create_fit_card, using the outfit suggestion from
    # step 5 and the item from step 4. State flows in again.
    session["fit_card"] = create_fit_card(
        outfit=session["outfit_suggestion"],
        new_item=session["selected_item"],
    )

    # Step 7 — return the completed session.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
