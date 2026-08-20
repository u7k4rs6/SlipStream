"""The orchestrator: the only module that decides a run is safe to commit."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from slipstream import emit, fetch, guards, schemas, sync

from conftest import FIXTURES

OFFLINE = FIXTURES / "offline"
DAY_ONE = date(2026, 8, 20)
DAY_TWO = date(2026, 8, 21)


def run(tmp_path, today=DAY_ONE, sha="sha-one", offline=OFFLINE, **kw):
    return sync.sync(
        tmp_path / "data", today=today, sha=sha, offline=offline,
        changelog_path=tmp_path / "CHANGELOG.md", **kw,
    )


def test_first_run_builds_the_whole_dataset(tmp_path):
    outcome = run(tmp_path)
    assert outcome.changed
    assert len(outcome.problems) == 13
    assert outcome.result.counts["added"] == 13
    assert (tmp_path / "data" / "problems.json").exists()


def test_readme_and_formats_pages_agree(tmp_path):
    """Zero divergence today; any drift is signal (D9)."""
    outcome = run(tmp_path)
    assert not [w for w in outcome.warnings if "diverge" in w]


def test_every_row_gets_a_format_from_the_right_source(tmp_path):
    """SQL and Coding share the /problems/ route, so only the column or the
    page identity can tell them apart."""
    outcome = run(tmp_path)
    formats = {p.title: p.format for p in outcome.problems.values()}
    assert formats["Customer Package Delivery Report"] == "SQL"
    assert formats["Buy Volumes"] == "Coding"
    assert formats["Design an In-Memory Job Scheduler"] == "Low-level design"


def test_rows_record_both_sources(tmp_path):
    outcome = run(tmp_path)
    row = [p for p in outcome.problems.values() if p.title == "Buy Volumes"][0]
    assert sorted(row.sources) == ["README.md", "formats/coding.md"]


def test_second_run_at_the_same_sha_does_nothing(tmp_path):
    run(tmp_path)
    outcome = run(tmp_path)
    assert outcome.skipped
    assert not outcome.changed


def test_forcing_a_rerun_at_the_same_sha_finds_no_changes(tmp_path):
    run(tmp_path)
    outcome = run(tmp_path, today=DAY_TWO, force=True)
    assert not outcome.skipped
    assert outcome.result.changes == []
    assert not outcome.changed


def test_a_new_sha_with_identical_content_still_commits_nothing(tmp_path):
    """Upstream commits hourly; content changes far less often."""
    run(tmp_path)
    outcome = run(tmp_path, today=DAY_TWO, sha="sha-two")
    assert not outcome.skipped
    assert not outcome.changed


def test_removal_is_tombstoned_across_runs(tmp_path):
    run(tmp_path)
    trimmed = tmp_path / "trimmed"
    trimmed.mkdir()
    for path in OFFLINE.iterdir():
        text = path.read_text()
        if path.name in ("README.md", "coding.md"):
            text = "\n".join(l for l in text.split("\n") if "amazon-buy-volumes" not in l)
        (trimmed / path.name).write_text(text)

    outcome = run(tmp_path, today=DAY_TWO, sha="sha-two", offline=trimmed)
    assert outcome.result.counts["removed"] == 1
    stone = [p for p in outcome.problems.values() if p.state == "removed"][0]
    assert stone.title == "Buy Volumes"
    assert stone.removed_on == "2026-08-21"
    archived = json.loads((tmp_path / "data" / "archive.json").read_text())
    assert archived["count"] == 1


def test_meta_records_the_sha_and_every_source_digest(tmp_path):
    run(tmp_path)
    meta = json.loads((tmp_path / "data" / "meta.json").read_text())
    assert meta["upstream_sha"] == "sha-one"
    assert set(meta["sources"]) == {
        "README.md", "assets/company-domains.json", "formats/ai-coding.md",
        "formats/coding.md", "formats/low-level-design.md", "formats/sql.md",
        "formats/system-design.md",
    }
    assert meta["counts"]["live"] == 13


def test_unknown_upstream_header_aborts_before_writing_anything(tmp_path):
    run(tmp_path)
    before = (tmp_path / "data" / "problems.json").read_bytes()

    broken = tmp_path / "broken"
    broken.mkdir()
    for path in OFFLINE.iterdir():
        text = path.read_text()
        if path.name == "README.md":
            text = text.replace("| Format |", "| Difficulty | Format |")
        (broken / path.name).write_text(text)

    with pytest.raises(schemas.UnknownSchemaError):
        run(tmp_path, today=DAY_TWO, sha="sha-two", offline=broken)
    assert (tmp_path / "data" / "problems.json").read_bytes() == before


def test_mass_row_loss_aborts_before_writing_anything(tmp_path):
    run(tmp_path)
    before = (tmp_path / "data" / "problems.json").read_bytes()

    gutted = tmp_path / "gutted"
    gutted.mkdir()
    for path in OFFLINE.iterdir():
        text = path.read_text()
        if path.suffix == ".md":
            head = [l for l in text.split("\n") if not l.startswith("| **")]
            keep = [l for l in text.split("\n") if "amazon-buy-volumes" in l]
            text = "\n".join(head[:-1] + keep) + "\n"
        (gutted / path.name).write_text(text)

    with pytest.raises(guards.SyncAbort, match="row count fell"):
        run(tmp_path, today=DAY_TWO, sha="sha-two", offline=gutted)
    assert (tmp_path / "data" / "problems.json").read_bytes() == before


def test_missing_source_file_aborts(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(fetch.FetchError, match="missing"):
        run(tmp_path, offline=empty)


def test_cli_reports_success(tmp_path, capsys):
    code = sync.main([
        "--data", str(tmp_path / "data"), "--offline", str(OFFLINE),
        "--sha", "sha-one", "--changelog", str(tmp_path / "CHANGELOG.md"),
    ])
    assert code == 0
    out = capsys.readouterr().out
    assert "13 live rows" in out
    assert "added=13" in out


def test_cli_returns_nonzero_on_abort(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    code = sync.main(["--data", str(tmp_path / "data"), "--offline", str(empty)])
    assert code == 1
    assert "SYNC ABORTED" in capsys.readouterr().err


def test_sync_never_touches_the_personal_layer(tmp_path):
    """FR-4: the sync job has no write path to personal data."""
    personal = tmp_path / "personal.json"
    personal.write_text('{"abc": {"status": "solved"}}')
    stamp = personal.stat().st_mtime_ns
    run(tmp_path)
    assert personal.read_text() == '{"abc": {"status": "solved"}}'
    assert personal.stat().st_mtime_ns == stamp
