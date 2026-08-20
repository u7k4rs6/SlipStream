"""Abort thresholds (FR-7, D9)."""

from __future__ import annotations

import pytest

from slipstream import guards
from slipstream.model import Problem


def _problem(pid: str, *, format="Coding", state="active") -> Problem:
    return Problem(
        id=pid, key=f"problems/{pid}", title=pid, url=f"https://x/problems/{pid}",
        companies=["Amazon"], format=format, upstream_updated="2026-08-01",
        first_seen="2026-08-01", last_seen="2026-08-21", state=state,
    )


def test_zero_rows_always_aborts():
    with pytest.raises(guards.SyncAbort, match="0 rows"):
        guards.check_row_count(1944, 0)


def test_zero_rows_aborts_even_from_an_empty_baseline():
    with pytest.raises(guards.SyncAbort):
        guards.check_row_count(0, 0)


def test_drop_above_ten_percent_aborts():
    with pytest.raises(guards.SyncAbort, match="1944"):
        guards.check_row_count(1944, 1700)


def test_drop_at_exactly_ten_percent_is_allowed():
    assert guards.check_row_count(1000, 900) == []


def test_small_drop_is_allowed():
    assert guards.check_row_count(1944, 1900) == []


def test_growth_is_never_an_abort():
    assert guards.check_row_count(1944, 2500) == []


def test_first_run_has_no_baseline_to_compare():
    assert guards.check_row_count(0, 1944) == []


def test_identical_sources_do_not_diverge():
    ids = {f"p{i}" for i in range(100)}
    assert guards.check_divergence(ids, set(ids)) == []


def test_small_divergence_warns_but_proceeds():
    readme = {f"p{i}" for i in range(2000)}
    formats = readme - {"p1", "p2", "p3"}
    warnings = guards.check_divergence(readme, formats)
    assert len(warnings) == 1
    assert "3 rows diverge" in warnings[0]


def test_divergence_above_the_floor_aborts():
    readme = {f"p{i}" for i in range(100)}
    formats = readme - {f"p{i}" for i in range(30)}
    with pytest.raises(guards.SyncAbort, match="30 rows diverge"):
        guards.check_divergence(readme, formats)


def test_divergence_limit_scales_with_dataset_size():
    """1% of 5,000 rows is 50, above the 25-row floor."""
    readme = {f"p{i}" for i in range(5000)}
    formats = readme - {f"p{i}" for i in range(40)}
    assert len(guards.check_divergence(readme, formats)) == 1
    formats = readme - {f"p{i}" for i in range(60)}
    with pytest.raises(guards.SyncAbort):
        guards.check_divergence(readme, formats)


def test_divergence_counts_both_directions():
    readme = {"a", "b"} | {f"p{i}" for i in range(100)}
    formats = {"c", "d"} | {f"p{i}" for i in range(100)}
    warnings = guards.check_divergence(readme, formats)
    assert "4 rows diverge" in warnings[0]


def test_unclassified_live_row_aborts():
    problems = {"a": _problem("a"), "b": _problem("b", format=None)}
    with pytest.raises(guards.SyncAbort, match="1 live rows have no format"):
        guards.check_unclassified(problems)


def test_unclassified_tombstone_is_exempt():
    """Pre-2026 layouts had no format column; their tombstones stay legal."""
    problems = {"a": _problem("a", format=None, state="removed")}
    assert guards.check_unclassified(problems) == []


def test_fully_classified_dataset_passes():
    assert guards.check_unclassified({"a": _problem("a")}) == []
