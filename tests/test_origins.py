"""Origin resolution: precision over coverage, and a deterministic artifact.

The property under test throughout is that a *wrong* link is worse than none.
Every case that could plausibly resolve two ways must resolve to nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slipstream import emit, origins
from slipstream.model import Problem

from conftest import FIXTURES


@pytest.fixture
def catalog():
    return origins.parse_catalog(
        (FIXTURES / "origin" / "leetcode-catalog.json").read_bytes()
    )


def problem(title: str, fmt: str = "Coding", key: str = None) -> Problem:
    from slipstream.model import derive_id

    key = key or f"problems/{title.lower().replace(' ', '-')}"
    return Problem(
        id=derive_id(key), key=key, title=title, url=f"https://www.fastprep.io/{key}",
        companies=["Amazon"], format=fmt, upstream_updated="2026-08-01",
        first_seen="2026-08-20", last_seen="2026-08-20",
    )


def as_map(*problems: Problem) -> dict[str, Problem]:
    return {p.id: p for p in problems}


# ---- matching -----------------------------------------------------------

def test_exact_title_matches_ignoring_case_and_punctuation(catalog):
    found = origins.match("number of islands", catalog)
    assert found.slug == "number-of-islands"
    assert found.url == "https://leetcode.com/problems/number-of-islands/"


def test_articles_and_word_order_do_not_block_a_match(catalog):
    assert origins.match("Search in a Rotated Sorted Array", catalog).slug == (
        "search-in-rotated-sorted-array"
    )
    assert origins.match("Reverse An Integer", catalog).slug == "reverse-integer"


def test_upstream_abbreviations_are_expanded(catalog):
    """Upstream writes "Num of", LeetCode writes "Number of". Pure spelling."""
    assert origins.match("Num of Good Pairs", catalog).slug == "number-of-good-pairs"


def test_a_plural_alone_does_not_block_a_match(catalog):
    assert origins.match("Merge Interval", catalog).slug == "merge-intervals"


def test_short_words_ending_in_s_are_not_treated_as_plurals(catalog):
    """A stemmer that turns "abs" into "ab" invents collisions instead of
    finding them, so anything this short is left alone."""
    assert origins._stem("abs") == "abs"
    assert origins._stem("gas") == "gas"
    assert origins._stem("intervals") == "interval"


def test_a_leading_verb_on_upstreams_side_is_dropped(catalog):
    assert origins.match("Is Happy Number", catalog).slug == "happy-number"
    assert origins.match("Implement an LRU Cache", catalog).slug == "lru-cache"


def test_a_leading_verb_on_leetcodes_side_is_not_dropped(catalog):
    """Stripping both sides would equate "Find Maximum Score" with LeetCode's
    "Get the Maximum Score" -- two different verbs, and a guess either way."""
    assert origins.match("Find Maximum Score", catalog) is None


def test_and_is_not_a_stopword(catalog):
    """LeetCode's "Maximum AND Sum of Array" is bitwise AND. Treating it as
    noise matched it to an upstream row about a plain maximum sum."""
    assert origins.match("Get Max Sum Arr", catalog) is None
    assert origins.match("Maximum AND Sum of Array", catalog).slug == (
        "maximum-and-sum-of-array"
    )


def test_an_extra_meaningful_token_is_not_a_match(catalog):
    """"Two Sum" and "Two Sum II" are different questions, and the whole
    difference between them is one token. Loosening this would mislink them."""
    assert origins.match("Two Sum III", catalog) is None


def test_unrelated_titles_do_not_resolve(catalog):
    assert origins.match("Get Optimal String Length", catalog) is None
    assert origins.match("Buy Volumes", catalog) is None
    assert origins.match("", catalog) is None


def test_a_title_shared_by_two_questions_resolves_to_neither(catalog):
    assert origins.match("Duplicate Title", catalog) is None


def test_premium_questions_are_flagged_not_hidden(catalog):
    """Premium is another sign-in wall, so the link is still worth having --
    but it has to announce itself rather than promise open access."""
    found = origins.match("Meeting Rooms II", catalog)
    assert found.paid is True
    assert found.to_dict()["paid"] is True
    assert "paid" not in origins.match("3Sum", catalog).to_dict()


def test_difficulty_rides_along_when_known(catalog):
    assert origins.match("Two Sum", catalog).to_dict()["difficulty"] == "Easy"


# ---- resolution over a dataset ------------------------------------------

def test_only_coding_and_sql_can_resolve(catalog):
    """"Design a Web Crawler" is a system-design prompt. LeetCode 1236 "Web
    Crawler" is an unrelated coding exercise that happens to share the name."""
    design = problem("Design a Web Crawler", "System design")
    coding = problem("Web Crawler", "Coding", key="problems/web-crawler")
    resolved = origins.resolve(as_map(design, coding), catalog)
    assert design.id not in resolved
    assert coding.id in resolved


def test_unmatched_problems_get_no_entry_at_all(catalog):
    problems = as_map(problem("3Sum"), problem("Get Query Answers"))
    resolved = origins.resolve(problems, catalog)
    assert len(resolved) == 1
    assert problem("Get Query Answers").id not in resolved


def test_document_is_sorted_and_carries_no_timestamp(catalog):
    problems = as_map(problem("Two Sum"), problem("3Sum"), problem("Number of Islands"))
    doc = origins.origins_document(origins.resolve(problems, catalog), catalog.size)
    assert list(doc["origins"]) == sorted(doc["origins"])
    assert doc["count"] == 3
    assert not any("time" in k or "date" in k for k in doc)


def test_rerunning_against_an_unchanged_catalogue_writes_nothing(catalog, tmp_path):
    problems = as_map(problem("Two Sum"), problem("Buy Volumes"))
    emit.write_text(
        tmp_path / "problems.json",
        emit.dumps_rows(emit.problems_document(problems), "problems"),
    )
    _, first = origins.build(tmp_path, catalog)
    _, second = origins.build(tmp_path, catalog)
    assert first is True and second is False


def test_refuses_to_run_against_an_empty_dataset(catalog, tmp_path):
    with pytest.raises(origins.OriginError):
        origins.build(tmp_path, catalog)


# ---- catalogue parsing ---------------------------------------------------

def test_a_catalogue_that_changed_shape_is_an_error_not_an_empty_map():
    with pytest.raises(origins.OriginError):
        origins.parse_catalog(json.dumps({"problems": []}))
    with pytest.raises(origins.OriginError):
        origins.parse_catalog(b"<html>429 Too Many Requests</html>")


def test_entries_missing_a_slug_are_skipped_not_fatal():
    catalog = origins.parse_catalog(json.dumps({
        "stat_status_pairs": [
            {"stat": {"question__title": "Broken"}, "paid_only": False},
            {"stat": {"question__title": "Fine", "question__title_slug": "fine"},
             "difficulty": {"level": 1}, "paid_only": False},
        ],
    }))
    assert origins.match("Broken", catalog) is None
    assert origins.match("Fine", catalog).slug == "fine"


def test_two_catalogue_titles_that_reduce_alike_both_drop_out():
    """Folding abbreviations and plurals can make distinct LeetCode titles
    collide. The unique-hit rule has to eat both, not pick one."""
    catalog = origins.parse_catalog(json.dumps({
        "stat_status_pairs": [
            {"stat": {"question__title": "Max Sum", "question__title_slug": "max-sum"},
             "difficulty": {"level": 1}, "paid_only": False},
            {"stat": {"question__title": "Maximum Sums", "question__title_slug": "maximum-sums"},
             "difficulty": {"level": 2}, "paid_only": False},
        ],
    }))
    assert origins.reduced("Max Sum") == origins.reduced("Maximum Sums")
    assert origins.match("Max Sums", catalog) is None
    # The exact title is still unambiguous, so it still resolves.
    assert origins.match("Max Sum", catalog).slug == "max-sum"


def test_a_title_of_nothing_but_stopwords_matches_nothing():
    """An empty fingerprint would otherwise meet any other empty one."""
    catalog = origins.parse_catalog(json.dumps({
        "stat_status_pairs": [
            {"stat": {"question__title": "The", "question__title_slug": "the"},
             "difficulty": {"level": 1}, "paid_only": False},
            {"stat": {"question__title": "Two Sum", "question__title_slug": "two-sum"},
             "difficulty": {"level": 1}, "paid_only": False},
        ],
    }))
    assert origins.reduced("Of The") == frozenset()
    assert origins.match("Of The", catalog) is None
