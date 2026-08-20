"""Emitted artifacts: determinism, reviewable diffs, and idempotent re-runs."""

from __future__ import annotations

import json
from datetime import date

import pytest

from slipstream import diff, emit, parse
from slipstream.model import Problem

from conftest import read_fixture

BEFORE_DAY = date(2026, 8, 20)
TODAY = date(2026, 8, 21)
STAMP = "2026-08-21T06:00:00Z"


def load(name: str, vocab, today: date) -> dict[str, Problem]:
    rows, report = parse.parse_document(read_fixture("synthetic", "diff", name), name)
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


@pytest.fixture
def meta():
    return emit.Meta(
        upstream_sha="d163035c",
        synced_at=STAMP,
        sources={"README.md": "a" * 64},
        warnings=[],
    )


@pytest.fixture
def emitted(tmp_path, result, meta):
    root = tmp_path / "data"
    report = emit.emit(root, result.problems, result, meta)
    return root, report


def read_doc(root, *parts):
    return json.loads(root.joinpath(*parts).read_text(encoding="utf-8"))


# --- the artifact set ---------------------------------------------------


def test_emits_the_full_artifact_set(emitted):
    root, _ = emitted
    for name in ("problems.json", "index.json", "archive.json", "meta.json"):
        assert (root / name).exists(), name
    assert (root / "changes" / "2026-08-21.json").exists()
    assert (root / "changes" / "latest.json").exists()
    assert (root.parent / "CHANGELOG.md").exists()


def test_every_artifact_is_valid_json(emitted):
    root, _ = emitted
    for path in root.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))


def test_problems_document_carries_every_row_including_tombstones(emitted, result):
    root, _ = emitted
    doc = read_doc(root, "problems.json")
    assert doc["count"] == len(result.problems) == 6
    assert any(p["state"] == "removed" for p in doc["problems"])


def test_problems_are_ordered_by_key_not_upstream_row_order(emitted):
    root, _ = emitted
    keys = [p["key"] for p in read_doc(root, "problems.json")["problems"]]
    assert keys == sorted(keys)


def test_problems_json_is_one_record_per_line(emitted):
    """A single compact line would make every daily diff look total."""
    root, _ = emitted
    lines = (root / "problems.json").read_text(encoding="utf-8").splitlines()
    records = [l for l in lines if l.startswith('{"id"')]
    assert len(records) == 6


def test_latest_matches_the_dated_change_file(emitted):
    root, _ = emitted
    assert read_doc(root, "changes", "latest.json") == read_doc(
        root, "changes", "2026-08-21.json"
    )


def test_change_document_reports_every_kind(emitted):
    root, _ = emitted
    doc = read_doc(root, "changes", "latest.json")
    assert doc["date"] == "2026-08-21"
    assert doc["counts"] == {
        "added": 1, "removed": 1, "retitled": 1, "relinked": 1, "recompanied": 1,
    }


def test_meta_records_provenance_and_counts(emitted):
    root, _ = emitted
    doc = read_doc(root, "meta.json")
    assert doc["upstream_sha"] == "d163035c"
    assert doc["synced_at"] == STAMP
    assert doc["sources"] == {"README.md": "a" * 64}
    assert doc["counts"] == {"live": 5, "tombstoned": 1, "total": 6}
    assert doc["changes"]["relinked"] == 1


def test_source_digest_is_sha256():
    import hashlib

    assert emit.source_digest("hello") == hashlib.sha256(b"hello").hexdigest()
    assert emit.source_digest("hello") == emit.source_digest(b"hello")


# --- search index -------------------------------------------------------


def test_index_postings_point_at_problems_json_positions(emitted):
    root, _ = emitted
    problems = read_doc(root, "problems.json")["problems"]
    index = read_doc(root, "index.json")
    for row in index["tokens"]["ledger"]:
        assert "ledger" in problems[row]["title"].lower()


def test_index_covers_titles_and_companies(emitted):
    root, _ = emitted
    tokens = read_doc(root, "index.json")["tokens"]
    assert "cursor" in tokens      # title
    assert "figma" in tokens       # company
    assert "google" in tokens      # company added by the recompany


def test_index_splits_multi_word_companies(vocab, tmp_path, meta):
    p = _problem("problems/x", companies=["Goldman Sachs", "Zomato / Eternal"])
    emit.emit(tmp_path, {p.id: p}, None, meta)
    tokens = json.loads((tmp_path / "index.json").read_text())["tokens"]
    assert {"goldman", "sachs", "zomato", "eternal"} <= set(tokens)


def test_prefix_map_starts_at_three_characters(emitted):
    root, _ = emitted
    index = read_doc(root, "index.json")
    assert index["min_prefix"] == 3
    assert min(len(p) for p in index["prefixes"]) == 3
    assert "led" in index["prefixes"]
    assert "ledger" in index["prefixes"]["led"]


def test_prefix_map_omits_the_whole_token(emitted):
    """A full token is already a key in `tokens`; repeating it wastes payload."""
    root, _ = emitted
    index = read_doc(root, "index.json")
    assert "ledger" in index["tokens"]
    assert {"led", "ledg", "ledge"} <= set(index["prefixes"])
    # No longer token starts with "ledger", so it must not appear as a prefix.
    assert "ledger" not in index["prefixes"]


def test_index_and_problems_agree_on_row_count(emitted):
    root, _ = emitted
    assert read_doc(root, "index.json")["count"] == read_doc(root, "problems.json")["count"]


def test_tokenize_strips_punctuation_and_case():
    assert emit.tokenize("Design a Web-Crawler (v2)") == [
        "design", "a", "web", "crawler", "v2",
    ]


# --- archive ------------------------------------------------------------


def test_archive_collects_tombstones_and_superseded_rows(emitted, result):
    root, _ = emitted
    archived = read_doc(root, "archive.json")["archived"]
    assert {e["id"] for e in archived} == {p.id for p in result.archived}
    assert len(archived) == 2


def test_archive_is_append_only_across_runs(tmp_path, before, after, meta):
    root = tmp_path / "data"
    first = diff.diff(before, after, TODAY)
    emit.emit(root, first.problems, first, meta)

    # A later day removes one more row; yesterday's entries must survive.
    later = dict(after)
    doomed = next(iter(later))
    del later[doomed]
    second = diff.diff(first.problems, later, date(2026, 8, 22))
    emit.emit(root, second.problems, second, meta)

    archived = json.loads((root / "archive.json").read_text())["archived"]
    assert len(archived) == 3
    assert doomed in {e["id"] for e in archived}


def test_archive_does_not_duplicate_on_a_same_day_rerun(emitted, result, meta):
    root, _ = emitted
    emit.emit(root, result.problems, result, meta)
    assert len(read_doc(root, "archive.json")["archived"]) == 2


def test_corrupt_archive_aborts_rather_than_overwriting_history(tmp_path, result, meta):
    """Treating a truncated archive as empty would destroy the permanent record."""
    root = tmp_path / "data"
    root.mkdir()
    (root / "archive.json").write_text('{"archived": [{"id": "abc"}', encoding="utf-8")
    with pytest.raises(emit.EmitError, match="not valid JSON"):
        emit.emit(root, result.problems, result, meta)
    assert (root / "archive.json").read_text().startswith('{"archived"')


def test_archive_of_the_wrong_shape_aborts(tmp_path, result, meta):
    root = tmp_path / "data"
    root.mkdir()
    (root / "archive.json").write_text('{"rows": []}', encoding="utf-8")
    with pytest.raises(emit.EmitError, match="not an archive document"):
        emit.emit(root, result.problems, result, meta)


# --- changelog ----------------------------------------------------------


def test_changelog_groups_by_kind(emitted):
    root, _ = emitted
    text = (root.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.startswith("# Changelog")
    assert "## 2026-08-21" in text
    for heading in ("Added (1)", "Removed (1)", "Retitled (1)", "Relinked (1)",
                    "Company changed (1)"):
        assert f"### {heading}" in text


def test_changelog_describes_each_kind_usefully(emitted):
    root, _ = emitted
    text = (root.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Design a Collaborative Cursor Layer — Figma · System design" in text
    assert "Concatenate Digit-wise Sums → Concatenate Digit-Wise Sums" in text
    assert "problems/stripe-ledger-reconciliation → problems/stripe-ledger-reconciliation-v2" in text
    assert "removed upstream" in text


def test_changelog_is_newest_first():
    older = emit.update_changelog("# Changelog\n", "## 2026-08-01\n\n- old\n", "2026-08-01")
    both = emit.update_changelog(older, "## 2026-08-21\n\n- new\n", "2026-08-21")
    assert both.index("## 2026-08-21") < both.index("## 2026-08-01")


def test_same_day_rerun_replaces_its_section_instead_of_stacking():
    once = emit.update_changelog("# Changelog\n", "## 2026-08-21\n\n- one\n", "2026-08-21")
    twice = emit.update_changelog(once, "## 2026-08-21\n\n- two\n", "2026-08-21")
    assert twice.count("## 2026-08-21") == 1
    assert "- two" in twice and "- one" not in twice


def test_changelog_untouched_when_nothing_changed(tmp_path, after, meta):
    root = tmp_path / "data"
    quiet = diff.diff(after, after, TODAY)
    emit.emit(root, quiet.problems, quiet, meta)
    assert not (root.parent / "CHANGELOG.md").exists()


def test_ambiguous_relinks_are_surfaced_for_confirmation(tmp_path, meta):
    old_a, old_b = _problem("problems/a"), _problem("problems/b")
    new_a, new_b = _problem("problems/a2"), _problem("problems/b2")
    result = diff.diff(
        {old_a.id: old_a, old_b.id: old_b}, {new_a.id: new_a, new_b.id: new_b}, TODAY
    )
    emit.emit(tmp_path / "data", result.problems, result, meta)
    text = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "### Needs confirmation (1)" in text
    assert "not merged" in text


# --- determinism and no-op runs ----------------------------------------


def test_identical_input_produces_byte_identical_files(tmp_path, result, meta):
    a, b = tmp_path / "a", tmp_path / "b"
    emit.emit(a, result.problems, result, meta)
    emit.emit(b, result.problems, result, meta)
    for path in sorted(a.rglob("*.json")):
        assert path.read_bytes() == (b / path.relative_to(a)).read_bytes(), path.name


def test_row_order_does_not_affect_output(tmp_path, result, meta):
    a, b = tmp_path / "a", tmp_path / "b"
    emit.emit(a, result.problems, result, meta)
    emit.emit(b, dict(reversed(list(result.problems.items()))), result, meta)
    assert (a / "problems.json").read_bytes() == (b / "problems.json").read_bytes()
    assert (a / "index.json").read_bytes() == (b / "index.json").read_bytes()


def test_rerunning_an_unchanged_sync_reports_no_dataset_change(tmp_path, result, meta):
    root = tmp_path / "data"
    first = emit.emit(root, result.problems, result, meta)
    assert first.dataset_changed

    second = emit.emit(root, result.problems, result, meta)
    assert not second.dataset_changed
    assert "problems.json" in second.unchanged


def test_meta_timestamp_alone_never_looks_like_a_change(tmp_path, result):
    """meta.json moves every run; gating a commit on it would commit daily noise."""
    root = tmp_path / "data"
    emit.emit(root, result.problems, result, emit.Meta("sha", "2026-08-21T06:00:00Z"))
    second = emit.emit(root, result.problems, result, emit.Meta("sha", "2026-08-22T06:00:00Z"))
    assert not second.dataset_changed
    assert "meta.json" in second.written


def test_unchanged_files_are_not_rewritten(tmp_path, result, meta):
    root = tmp_path / "data"
    emit.emit(root, result.problems, result, meta)
    stamp = (root / "problems.json").stat().st_mtime_ns
    emit.emit(root, result.problems, result, meta)
    assert (root / "problems.json").stat().st_mtime_ns == stamp


def test_emit_works_without_a_diff(tmp_path, after, meta):
    """First-ever run: a dataset exists but there is nothing to compare against."""
    report = emit.emit(tmp_path / "data", after, None, meta)
    assert report.dataset_changed
    assert not (tmp_path / "data" / "changes").exists()
    assert read_doc(tmp_path / "data", "meta.json")["counts"]["live"] == 5


def _problem(key, *, title="Two Sum", companies=("Amazon",), format="Coding") -> Problem:
    from slipstream import model

    return Problem(
        id=model.derive_id(key), key=key, title=title,
        url=f"https://www.fastprep.io/{key}", companies=list(companies),
        format=format, upstream_updated="2026-08-01",
        first_seen="2026-08-20", last_seen="2026-08-21",
    )
