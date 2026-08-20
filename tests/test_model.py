"""Dates, freshness markers, and the derived stable key."""

from __future__ import annotations

from datetime import date

from slipstream import model


def test_parses_the_current_date_shape():
    assert model.parse_updated("Nov 23, 2024") == date(2024, 11, 23)


def test_parses_the_2023_extra_comma_shape():
    assert model.parse_updated("Aug, 31, 2023") == date(2023, 8, 31)


def test_freshness_markers_do_not_block_the_date():
    assert model.parse_updated("\U0001f525 Aug 12, 2026") == date(2026, 8, 12)
    assert model.parse_updated("\U0001f195 Jul 15, 2026") == date(2026, 7, 15)


def test_impossible_dates_are_rejected_not_clamped():
    assert model.parse_updated("Feb 30, 2026") is None


def test_unparseable_cell_returns_none():
    assert model.parse_updated("") is None
    assert model.parse_updated("soon") is None
    assert model.parse_updated("Foo 12, 2026") is None


def test_strip_markers_leaves_plain_text():
    assert model.strip_markers("\U0001f525  Aug 12, 2026 ") == "Aug 12, 2026"


def test_key_is_namespace_and_slug():
    key = model.derive_key("https://www.fastprep.io/problems/amazon-buy-volumes")
    assert key == "problems/amazon-buy-volumes"


def test_key_ignores_host_query_and_fragment():
    a = model.derive_key("https://www.fastprep.io/problems/amazon-buy-volumes")
    b = model.derive_key("http://fastprep.io/problems/amazon-buy-volumes?ref=readme#top")
    assert a == b


def test_key_collapses_deep_historical_paths_to_first_and_last():
    assert model.derive_key("https://fastprep.gitbook.io/oa/company/amazon/buy-volumes") == (
        "oa/buy-volumes"
    )


def test_key_is_none_without_a_usable_path():
    assert model.derive_key("") is None
    assert model.derive_key("https://www.fastprep.io/") is None


def test_id_is_stable_and_short():
    key = "problems/amazon-buy-volumes"
    assert model.derive_id(key) == model.derive_id(key)
    assert len(model.derive_id(key)) == model.ID_LENGTH


def test_different_keys_get_different_ids():
    assert model.derive_id("problems/a") != model.derive_id("problems/b")


def test_fallback_key_is_namespaced_and_order_insensitive():
    a = model.fallback_key("Get Mean Rank Count", ["Amazon", "Meta"])
    b = model.fallback_key("get mean  rank count", ["Meta", "Amazon"])
    assert a == b
    assert a.startswith("untitled:")


def test_problem_round_trips_through_dict():
    p = model.Problem(
        id="abc", key="problems/x", title="X", url="https://x/problems/x",
        companies=["Amazon"], format="Coding", upstream_updated="2026-01-01",
        first_seen="2026-01-02", last_seen="2026-01-02",
    )
    assert model.Problem.from_dict(p.to_dict()) == p


def test_from_dict_ignores_unknown_fields():
    p = model.Problem(
        id="abc", key="k", title="X", url=None, companies=[], format=None,
        upstream_updated=None, first_seen="2026-01-01", last_seen="2026-01-01",
    )
    d = p.to_dict() | {"future_field_upstream_added": 1}
    assert model.Problem.from_dict(d) == p
