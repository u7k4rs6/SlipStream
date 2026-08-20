"""Diff classification — where personal data is preserved or orphaned."""

from __future__ import annotations

from datetime import date

import pytest

from slipstream import diff, parse
from slipstream.model import Problem

from conftest import read_fixture

BEFORE_DAY = date(2026, 8, 20)
TODAY = date(2026, 8, 21)


def load(name: str, vocab, today: date) -> dict[str, Problem]:
    rows, report = parse.parse_document(
        read_fixture("synthetic", "diff", name), name
    )
    return parse.normalize(rows, vocab, today, report)


@pytest.fixture
def before(vocab):
    return load("before.md", vocab, BEFORE_DAY)


@pytest.fixture
def after(vocab):
    return load("after.md", vocab, TODAY)


@pytest.fixture
def result(before, after):
    return diff.diff(before, after, TODAY)


def by_title(changes):
    return {c.title: c for c in changes}


# --- classification -----------------------------------------------------


def test_the_fixture_pair_classifies_one_of_each(result):
    assert result.counts == {
        diff.ADDED: 1,
        diff.REMOVED: 1,
        diff.RETITLED: 1,
        diff.RELINKED: 1,
        diff.RECOMPANIED: 1,
    }


def test_added_row_is_reported(result):
    added = result.of_kind(diff.ADDED)[0]
    assert added.title == "Design a Collaborative Cursor Layer"
    assert added.key == "system-design/collaborative-cursor-layer"


def test_removed_row_is_reported(result):
    removed = result.of_kind(diff.REMOVED)[0]
    assert removed.title == "Minimum Satellite Data Transfer Iterations"


def test_retitle_keeps_the_same_id(result, before, after):
    retitled = result.of_kind(diff.RETITLED)[0]
    assert retitled.before == {"title": "Concatenate Digit-wise Sums"}
    assert retitled.after == {"title": "Concatenate Digit-Wise Sums"}
    # The whole reason for slug-keying: the ID does not move under a retitle.
    assert retitled.id in before and retitled.id in after


def test_recompanied_reports_both_sides(result):
    changed = result.of_kind(diff.RECOMPANIED)[0]
    assert changed.before == {"companies": ["Meta"]}
    assert set(changed.after["companies"]) == {"Meta", "Google"}


def test_company_reordering_alone_is_not_a_change(vocab):
    a = _problem("k", companies=["Meta", "Google"])
    b = _problem("k", companies=["Google", "Meta"])
    result = diff.diff({a.id: a}, {b.id: b}, TODAY)
    assert result.changes == []


def test_unchanged_rows_produce_no_changes(result):
    assert "Buy Volumes" not in by_title(result.changes)


# --- relinks (D10) ------------------------------------------------------


def test_relink_is_reported_instead_of_add_plus_remove(result):
    relinked = result.of_kind(diff.RELINKED)[0]
    assert relinked.title == "Ledger Reconciliation"
    assert relinked.before["key"] == "problems/stripe-ledger-reconciliation"
    assert relinked.after["key"] == "problems/stripe-ledger-reconciliation-v2"
    # It must not also show up as an add or a remove.
    assert [c.title for c in result.of_kind(diff.ADDED)] == [
        "Design a Collaborative Cursor Layer"
    ]
    assert [c.title for c in result.of_kind(diff.REMOVED)] == [
        "Minimum Satellite Data Transfer Iterations"
    ]


def test_relink_writes_the_old_id_as_an_alias(result):
    relinked = result.of_kind(diff.RELINKED)[0]
    new = result.problems[relinked.id]
    assert relinked.previous_id in new.aliases


def test_relink_carries_first_seen_forward(result, before):
    relinked = result.of_kind(diff.RELINKED)[0]
    old = before[relinked.previous_id]
    assert result.problems[relinked.id].first_seen == old.first_seen == "2026-08-20"


def test_relinked_old_id_leaves_the_hot_dataset(result):
    relinked = result.of_kind(diff.RELINKED)[0]
    assert relinked.previous_id not in result.problems
    assert relinked.previous_id in {p.id for p in result.archived}


def test_relink_needs_an_exact_signature_match():
    """A different format is not the same problem, however similar the title."""
    old = _problem("problems/x", title="Ledger Reconciliation", format="Coding")
    new = _problem("problems/x-v2", title="Ledger Reconciliation", format="SQL")
    result = diff.diff({old.id: old}, {new.id: new}, TODAY)
    assert result.counts[diff.RELINKED] == 0
    assert result.counts[diff.ADDED] == 1
    assert result.counts[diff.REMOVED] == 1


def test_ambiguous_relink_is_surfaced_never_merged():
    """Two identical-signature candidates: guessing could orphan personal data."""
    old_a = _problem("problems/a", title="Two Sum", companies=["Amazon"])
    old_b = _problem("problems/b", title="Two Sum", companies=["Amazon"])
    new_a = _problem("problems/a2", title="Two Sum", companies=["Amazon"])
    new_b = _problem("problems/b2", title="Two Sum", companies=["Amazon"])
    result = diff.diff(
        {old_a.id: old_a, old_b.id: old_b},
        {new_a.id: new_a, new_b.id: new_b},
        TODAY,
    )
    assert result.counts[diff.RELINKED] == 0
    assert result.counts[diff.ADDED] == 2
    assert result.counts[diff.REMOVED] == 2
    assert len(result.ambiguous_relinks) == 1
    amb = result.ambiguous_relinks[0]
    assert amb.title == "Two Sum"
    assert len(amb.added_ids) == 2 and len(amb.removed_ids) == 2


# --- next-state bookkeeping ---------------------------------------------


def test_removed_rows_are_tombstoned_not_deleted(result):
    removed = result.of_kind(diff.REMOVED)[0]
    stone = result.problems[removed.id]
    assert stone.state == "removed"
    assert stone.removed_on == "2026-08-21"
    # last_seen stays at the last day it was actually present.
    assert stone.last_seen == "2026-08-20"


def test_every_tombstone_is_archived(result):
    removed = result.of_kind(diff.REMOVED)[0]
    assert removed.id in {p.id for p in result.archived}


def test_surviving_rows_keep_first_seen_and_advance_last_seen(result, before):
    pid = [c.id for c in result.of_kind(diff.RETITLED)][0]
    assert result.problems[pid].first_seen == before[pid].first_seen
    assert result.problems[pid].last_seen == "2026-08-21"


def test_upstream_fields_are_taken_from_today(result):
    pid = result.of_kind(diff.RETITLED)[0].id
    assert result.problems[pid].title == "Concatenate Digit-Wise Sums"
    assert result.problems[pid].upstream_updated == "2026-08-20"


def test_older_tombstones_are_carried_through(before, after):
    ghost = _problem("problems/gone", title="Ancient")
    ghost.state = "removed"
    ghost.removed_on = "2026-01-01"
    result = diff.diff({**before, ghost.id: ghost}, after, TODAY)
    assert result.problems[ghost.id].state == "removed"
    assert result.problems[ghost.id].removed_on == "2026-01-01"
    assert ghost.id not in {c.id for c in result.of_kind(diff.REMOVED)}


def test_a_tombstoned_row_that_reappears_is_restored():
    was = _problem("problems/x", first_seen="2026-01-01", last_seen="2026-02-01")
    was.state = "removed"
    was.removed_on = "2026-02-02"
    now = _problem("problems/x", first_seen="2026-08-21", last_seen="2026-08-21")
    result = diff.diff({was.id: was}, {now.id: now}, TODAY)
    restored = result.problems[now.id]
    assert restored.state == "active"
    assert restored.removed_on is None
    assert restored.first_seen == "2026-01-01"   # date added must not lie
    assert result.counts[diff.ADDED] == 1


def test_diff_is_idempotent(after):
    """Re-running against an unchanged upstream produces no changes at all."""
    first = diff.diff(after, after, TODAY)
    assert first.changes == []
    second = diff.diff(first.problems, after, TODAY)
    assert second.changes == []
    assert {k: v.to_dict() for k, v in second.problems.items()} == {
        k: v.to_dict() for k, v in first.problems.items()
    }


def test_changes_are_ordered_deterministically(before, after):
    a = diff.diff(before, after, TODAY)
    b = diff.diff(before, dict(reversed(list(after.items()))), TODAY)
    assert [c.to_dict() for c in a.changes] == [c.to_dict() for c in b.changes]


def test_result_serializes_to_json_ready_dict(result):
    import json

    doc = result.to_dict()
    assert doc["date"] == "2026-08-21"
    assert doc["counts"][diff.RELINKED] == 1
    json.dumps(doc)  # must not raise


# --- tombstone retention (D7) -------------------------------------------


def test_unreferenced_tombstone_ages_out_after_180_days():
    stale = _tombstone("problems/old", removed_on="2026-01-01")
    kept, dropped = diff.prune_tombstones(
        {stale.id: stale}, TODAY, referenced_ids=set()
    )
    assert kept == {}
    assert [p.id for p in dropped] == [stale.id]


def test_referenced_tombstone_is_kept_forever():
    stale = _tombstone("problems/old", removed_on="2020-01-01")
    kept, dropped = diff.prune_tombstones(
        {stale.id: stale}, TODAY, referenced_ids={stale.id}
    )
    assert stale.id in kept
    assert dropped == []


def test_recent_tombstone_is_kept():
    fresh = _tombstone("problems/recent", removed_on="2026-08-01")
    kept, dropped = diff.prune_tombstones(
        {fresh.id: fresh}, TODAY, referenced_ids=set()
    )
    assert fresh.id in kept and dropped == []


def test_active_rows_are_never_pruned():
    live = _problem("problems/live")
    kept, dropped = diff.prune_tombstones({live.id: live}, TODAY, referenced_ids=set())
    assert live.id in kept and dropped == []


def test_nothing_is_pruned_when_personal_references_are_unknown():
    """The sync holds no credential for the personal repo (D2), so it cannot
    prove a tombstone is unreferenced -- and must not guess."""
    stale = _tombstone("problems/old", removed_on="2020-01-01")
    kept, dropped = diff.prune_tombstones({stale.id: stale}, TODAY)
    assert stale.id in kept and dropped == []


# --- helpers ------------------------------------------------------------


def _problem(key, *, title="Title", companies=("Amazon",), format="Coding",
             first_seen="2026-08-20", last_seen="2026-08-20") -> Problem:
    from slipstream import model

    return Problem(
        id=model.derive_id(key),
        key=key,
        title=title,
        url=f"https://www.fastprep.io/{key}",
        companies=list(companies),
        format=format,
        upstream_updated="2026-08-01",
        first_seen=first_seen,
        last_seen=last_seen,
    )


def _tombstone(key, *, removed_on) -> Problem:
    p = _problem(key)
    p.state = "removed"
    p.removed_on = removed_on
    return p
