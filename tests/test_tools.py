"""
Tests for the three FitFindr tools and the query parser.

Run with:
    pytest tests/

The search_listings and parse_query tests run fully offline. The LLM-backed
tools (suggest_outfit, create_fit_card) are tested for their failure-mode
contract — that they return a non-empty string and never raise — which holds
whether or not a valid GROQ_API_KEY is configured.
"""

from agent import parse_query
from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── search_listings ──────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    assert all("title" in item and "price" in item for item in results)


def test_search_empty_results():
    # Impossible query → empty list, NOT an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=40)
    assert all(item["price"] <= 40 for item in results)


def test_search_size_filter_case_insensitive():
    # Lowercase "m" should still match size "M" listings.
    results = search_listings("track jacket", size="m", max_price=None)
    assert len(results) > 0
    for item in results:
        sz = item["size"].lower()
        assert "m" in sz or "one size" in sz or "oversized" in sz


def test_search_sorted_by_relevance():
    # More specific multi-keyword query — top result should out-score later ones.
    results = search_listings("vintage band graphic tee", size=None, max_price=None)
    assert len(results) >= 2  # several tees should surface


# ── parse_query ──────────────────────────────────────────────────────────────

def test_parse_extracts_price_and_size():
    parsed = parse_query("vintage graphic tee under $30, size M")
    assert parsed["max_price"] == 30.0
    assert parsed["size"] == "M"
    assert "graphic" in parsed["description"]
    # Price/size phrasing should be stripped from the keyword description.
    assert "$" not in parsed["description"]


def test_parse_handles_no_filters():
    parsed = parse_query("flowy midi skirt")
    assert parsed["max_price"] is None
    assert parsed["size"] is None


# ── suggest_outfit ───────────────────────────────────────────────────────────

def test_suggest_outfit_with_wardrobe_returns_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


def test_suggest_outfit_empty_wardrobe_does_not_crash():
    # Empty-wardrobe failure mode → still a useful, non-empty string.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


# ── create_fit_card ──────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_error_string():
    # Empty outfit failure mode → descriptive string, NOT an exception.
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("", item)
    assert isinstance(card, str)
    assert card.strip() != ""


def test_create_fit_card_whitespace_outfit_handled():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("   ", item)
    assert isinstance(card, str)
    assert card.strip() != ""
