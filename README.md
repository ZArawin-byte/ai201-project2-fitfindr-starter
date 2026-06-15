# FitFindr 🛍️

A multi-tool AI agent that helps you find secondhand clothing and figure out how to wear it.
You describe what you want in plain language; FitFindr searches a mock listings dataset,
styles the best find against your wardrobe, and writes a shareable "fit card" caption — with
graceful handling when a tool comes up empty.

Built for AI201 Project 2 (Week 2 — Multi-Tool AI Agents).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the repo root with a **Groq** API key (free at
[console.groq.com](https://console.groq.com); keys start with `gsk_`):

```
GROQ_API_KEY=gsk_your_key_here
```

Run it:

```bash
python app.py          # launches the Gradio UI (URL printed in terminal)
python agent.py        # CLI: runs a happy-path and a no-results interaction
pytest tests/          # runs the tool test suite
```

## Tool Inventory

| Tool | Inputs | Output | Purpose |
|------|--------|--------|---------|
| `search_listings` | `description` (str), `size` (str \| None), `max_price` (float \| None) | `list[dict]` of listing dicts (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted by relevance; `[]` if none match | Finds secondhand items matching keywords, size, and price ceiling |
| `suggest_outfit` | `new_item` (dict), `wardrobe` (dict) | `str` — 1–2 outfit suggestions | Styles the found item against the user's wardrobe (or gives general advice if the wardrobe is empty) |
| `create_fit_card` | `outfit` (str), `new_item` (dict) | `str` — a 2–4 sentence shareable caption | Writes an authentic OOTD-style social caption for the find |

The documented inputs/outputs match the actual function signatures in `tools.py`.

## How the Planning Loop Works

`run_agent(query, wardrobe)` in `agent.py` drives the agent. It is **conditional**, not a
fixed sequence:

1. `parse_query` extracts `description`, `size`, and `max_price` from the free-text query
   with regex (deterministic, no LLM call).
2. It calls `search_listings`. **This is the branch point:**
   - If results are empty → it sets `session["error"]` with concrete fixes (raise budget,
     drop the size filter, broaden keywords) and **returns immediately**. The styling tools
     are never called with empty input.
   - If results exist → it stores the top result as `session["selected_item"]` and continues.
3. It calls `suggest_outfit(selected_item, wardrobe)` and stores `outfit_suggestion`.
4. It calls `create_fit_card(outfit_suggestion, selected_item)` and stores `fit_card`.
5. It returns the session.

So an impossible query exits after one tool call; a matching query runs all three. See the
ASCII diagram in `planning.md` for the full control/data flow.

## State Management

A single `session` dict (built by `_new_session`) is the source of truth for one interaction.
It tracks `query`, `parsed`, `search_results`, `selected_item`, `wardrobe`,
`outfit_suggestion`, `fit_card`, and `error`. Each tool reads from it and writes its result
back, so state flows between tools without the user re-entering anything:
`search_listings` → `selected_item` → into `suggest_outfit` → `outfit_suggestion` → into
`create_fit_card` → `fit_card`. `app.py` reads the final session to fill the three UI panels.

## Error Handling (per tool)

- **`search_listings` — no matches:** returns `[]` (never raises); the loop converts that to
  a user-facing message and stops early.
  *Concrete example from testing:* the query `designer ballgown size XXS under $5` returns
  `[]`, and `agent.py` produces:
  `No listings matched "designer ballgown size XXS under $5". Try raising your $5 budget, or
  removing the size XXS filter, or trying broader keywords.` — and `fit_card` stays `None`.
- **`suggest_outfit` — empty wardrobe:** detects an empty `items` list and switches to a
  general-styling prompt, returning useful advice instead of crashing. On an LLM/API error it
  returns a plain fallback styling line.
- **`create_fit_card` — missing outfit:** guards an empty/whitespace `outfit` and returns a
  descriptive error string with no LLM call; on an LLM/API error it returns a templated
  fallback caption.

Every failure mode is covered by a test in `tests/test_tools.py`.

## Spec Reflection

- **One way the spec helped:** writing the Planning Loop section in `planning.md` as explicit
  branches ("if results empty, set error and return; else set selected_item and proceed")
  meant `run_agent` was almost a transcription of the spec — the early-return-before-styling
  rule was decided on paper, not discovered mid-coding.
- **One way implementation diverged:** the spec left query parsing open ("regex or LLM"). I
  chose regex in a dedicated `parse_query` helper so the loop stays fast and fully
  deterministic (and testable offline), rather than spending an LLM round-trip on parsing.
  This added a parsing step to the loop that the original diagram folded into "search".

## AI Usage

1. **Tool implementations (Milestone 3):** I gave Claude the Tool 1/2/3 spec blocks from
   `planning.md` one at a time and asked it to implement each against the `tools.py` stub
   signatures using `load_listings()` and `llama-3.3-70b-versatile`. I reviewed each function
   against my spec before trusting it and **changed**: the relevance scoring (I had it add a
   stopword list and score across title/description/tags/colors/brand rather than title-only),
   and I tightened the empty-wardrobe and empty-outfit guards into early returns. Verified with
   the pytest suite.
2. **Planning loop (Milestone 4):** I gave Claude the Planning Loop + State Management sections
   and the ASCII diagram and asked for `run_agent`. I **overrode** its first version, which
   called all three tools and only checked for errors at the end; I rewrote it to branch on the
   `search_listings` result and return early so the styling tools never run on empty input.
   Verified by running `python agent.py` and confirming the no-results query exits with
   `error` set and `fit_card == None`.
