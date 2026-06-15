# FitFindr — planning.md

> Written before implementation. This spec + the agent diagram are what I used
> to direct the AI tool (Claude) when generating the implementation.

---

## A Complete Interaction (high level)

FitFindr takes one natural-language request ("vintage graphic tee under $30, size M,
I wear baggy jeans and chunky sneakers"), parses it into search parameters, and runs a
three-tool pipeline: `search_listings` finds matching secondhand items, `suggest_outfit`
styles the top find against the user's wardrobe, and `create_fit_card` writes a shareable
caption. State flows through a single `session` dict so each tool builds on the last.
**Trigger logic:** search always runs first; if it returns nothing the agent stops and
explains what to change (it never calls the styling tools with empty input); otherwise it
proceeds through outfit and fit-card generation.

---

## Tools

### Tool 1: search_listings

**What it does:** Searches the 40-item mock listings dataset for pieces matching the
user's keywords, optional size, and optional price ceiling, ranked by relevance.

**Input parameters:**
- `description` (str): keywords describing the wanted item (e.g. "vintage graphic tee").
- `size` (str | None): size to filter on, case-insensitive substring match (e.g. "M"
  matches "S/M"). `None` skips size filtering.
- `max_price` (float | None): inclusive price ceiling. `None` skips price filtering.

**What it returns:** A `list[dict]` of full listing dicts (`id`, `title`, `description`,
`category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`),
sorted by keyword-overlap score, highest first. Listings scoring 0 are dropped. Returns
`[]` when nothing matches — never raises.

**What happens if it fails or returns nothing:** Returns an empty list. The planning loop
detects `[]`, sets a helpful `session["error"]` ("No listings matched … try raising your
budget / removing the size filter / broader keywords"), and stops before the styling tools.

---

### Tool 2: suggest_outfit

**What it does:** Uses the LLM to style a specific found item into 1–2 complete outfits,
referencing named pieces from the user's wardrobe when one is provided.

**Input parameters:**
- `new_item` (dict): the listing dict selected by the planning loop.
- `wardrobe` (dict): a wardrobe dict with an `items` list (may be empty).

**What it returns:** A non-empty `str` of outfit suggestions. With a wardrobe, it names
specific owned pieces; with an empty wardrobe, it gives general styling advice using
common staples.

**What happens if it fails or returns nothing:** Empty wardrobe → general-advice prompt
(handled, not an error). If the LLM call errors or returns blank, it returns a plain-text
fallback styling sentence rather than crashing or returning "".

---

### Tool 3: create_fit_card

**What it does:** Uses the LLM (higher temperature) to write a short, shareable OOTD-style
caption for the find, naming the item, price, and platform once each.

**Input parameters:**
- `outfit` (str): the outfit suggestion string from `suggest_outfit`.
- `new_item` (dict): the listing dict, for item name / price / platform.

**What it returns:** A 2–4 sentence caption `str`, varying across runs and inputs.

**What happens if it fails or returns nothing:** If `outfit` is empty/whitespace, returns
a descriptive error string (no LLM call). If the LLM call errors, returns a templated
fallback caption. Never raises.

---

### Additional Tools (if any)

None for the required build. (Stretch ideas considered: a `price_check` comparable-pricing
tool and loosened-constraint retry — see Error Handling notes.)

---

## Planning Loop

**How does your agent decide which tool to call next?** The loop is driven by what each
step returns, tracked in `session`:

1. Parse the query (`parse_query`) into `description`, `size`, `max_price` via regex.
2. Call `search_listings`. **Branch on the result:**
   - `search_results == []` → set `session["error"]` and **return early**. The outfit and
     fit-card tools are never called with empty input.
   - otherwise → `session["selected_item"] = search_results[0]` (top relevance) and continue.
3. Call `suggest_outfit(selected_item, wardrobe)` → store `outfit_suggestion`.
4. Call `create_fit_card(outfit_suggestion, selected_item)` → store `fit_card`.
5. Return the session.

The behavior is conditional, not a fixed sequence: an impossible query exits after one tool
call with an error; a matching query runs all three. Termination is guaranteed — the loop is
linear with a single early-exit branch, no retries that could spin.

---

## State Management

A single `session` dict (created by `_new_session`) is the source of truth for one
interaction. It stores: `query`, `parsed` (description/size/max_price), `search_results`,
`selected_item`, `wardrobe`, `outfit_suggestion`, `fit_card`, and `error`. Each tool reads
what it needs from the session and writes its result back: `selected_item` (set from search)
flows into `suggest_outfit`; `outfit_suggestion` (set from that) flows into `create_fit_card`.
The user never re-enters the item between steps — it is carried in `session`. `app.py` reads
the final session to populate the three UI panels.

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Returns `[]`; loop sets `session["error"]` with concrete suggestions (raise budget, drop size filter, broaden keywords) and stops before the styling tools. |
| suggest_outfit | Wardrobe is empty | Detects empty `items`, switches to a general-styling prompt and returns useful advice (a non-empty string), never crashes. On LLM/API error, returns a plain fallback styling line. |
| create_fit_card | Outfit input is missing or incomplete | Guards empty/whitespace `outfit` and returns a descriptive error string (no LLM call). On LLM/API error, returns a templated fallback caption. |

---

## Architecture

```
User query (text)  +  wardrobe choice
        │
        ▼
parse_query()  →  {description, size, max_price}
        │
        ▼
Planning Loop (run_agent) ─────────────────────────────────────────────┐
        │                                                               │
        ├─► search_listings(description, size, max_price)               │
        │        │ results == []                                        │
        │        ├──► session["error"] = "No listings… try …" → RETURN ─┤ (error
        │        │                                                      │  path)
        │        │ results == [item, ...]                               │
        │        ▼                                                      │
        │   session["selected_item"] = results[0]                       │
        │        │                                                      │
        ├─► suggest_outfit(selected_item, wardrobe)                     │
        │        │   (empty wardrobe → general advice branch)           │
        │        ▼                                                      │
        │   session["outfit_suggestion"] = "..."                        │
        │        │                                                      │
        └─► create_fit_card(outfit_suggestion, selected_item)           │
                 │   (empty outfit → error-string guard)                │
                 ▼                                                      │
            session["fit_card"] = "..."                                 │
                 │                                                      │
                 ▼                                                      ▼
         Return session  ◄───────────────────────────────────── error returns here
                 │
                 ▼
         app.py maps session → 3 UI panels (listing / outfit / fit card)

      Session dict = shared state read+written by every step above.
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:** Tool used — **Claude**. Input —
the Tool 1/2/3 spec blocks above (inputs, return value, failure mode), one tool at a time,
plus the instruction to use `load_listings()` from the data loader and `llama-3.3-70b-versatile`
for the LLM tools. Expected output — three functions matching the stub signatures in
`tools.py`. Verification — for `search_listings`, run 3 queries (a normal match, a price-
filtered query, and an impossible query) and confirm filtering + empty-list behavior; for the
LLM tools, confirm they return non-empty strings and that the empty-wardrobe / empty-outfit
guards fire without raising. Codified as the pytest suite in `tests/`.

**Milestone 4 — Planning loop and state management:** Tool used — **Claude**. Input — the
Planning Loop and State Management sections plus the ASCII diagram above. Expected output — a
`run_agent` that parses the query, branches on `search_listings`, stores each result in
`session`, and returns early on no results. Verification — run `python agent.py` and confirm
the happy path fills `selected_item` → `outfit_suggestion` → `fit_card` while the impossible
query exits with `session["error"]` set and `fit_card` left `None`.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy
jeans and chunky sneakers. What's out there and how would I style it?"

**Step 0 — parse:** `parse_query` → `description="vintage graphic tee … baggy jeans chunky
sneakers"`, `size=None`, `max_price=30.0`.

**Step 1 — search:** `search_listings(description, None, 30.0)`. Returns the tees scoring on
"vintage/graphic/tee" under $30, ranked. Top result stored as `session["selected_item"]`
(e.g. a Y2K/graphic tee around $18–24).

**Step 2 — suggest outfit:** `suggest_outfit(selected_item, example_wardrobe)`. The LLM pairs
the tee with named wardrobe pieces ("baggy straight-leg jeans", "chunky white sneakers"),
returns a 3–4 sentence styling suggestion stored as `session["outfit_suggestion"]`.

**Step 3 — fit card:** `create_fit_card(outfit_suggestion, selected_item)`. The LLM writes a
casual caption mentioning the item, its price, and platform once each, stored as
`session["fit_card"]`.

**Final output to user:** three panels — the listing details, the outfit idea, and the
shareable fit card. (Error variant: had the query been "designer ballgown size XXS under $5",
Step 1 returns `[]`, the agent sets `session["error"]` and the first panel shows the
suggestion to loosen filters; the other two panels stay empty.)
