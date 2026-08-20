"""Parsing and normalisation, pinned against real upstream bytes."""

from __future__ import annotations

from datetime import date

import pytest

from slipstream import parse, schemas

from conftest import read_fixture

TODAY = date(2026, 8, 20)

# Every pinned fixture, with the row count it must yield. A fixture that starts
# yielding a different count means either upstream changed or we broke the
# parser -- both are worth failing over.
UPSTREAM_FIXTURES = [
    ("readme-5col-current.md", 16),
    ("readme-5col-practice-format.md", 6),
    ("readme-4col-oa-interview.md", 6),
    ("readme-4col-updated-time.md", 6),
    ("readme-4col-uploaded-time.md", 6),
    ("readme-4col-practice-beta.md", 6),
    ("readme-3col-gitbook.md", 6),
    ("formats-coding-4col.md", 8),
    ("formats-sql-4col.md", 2),
]


def parse_fixture(name: str, *, format_hint: str | None = None):
    return parse.parse_document(read_fixture("upstream", name), name, format_hint)


@pytest.mark.parametrize("name,expected", UPSTREAM_FIXTURES)
def test_every_known_schema_parses_every_row(name, expected):
    rows, report = parse_fixture(name)
    assert report.rows_seen == expected
    assert report.rows_parsed == expected
    assert report.skipped == []


@pytest.mark.parametrize("name,_expected", UPSTREAM_FIXTURES)
def test_every_row_has_a_title(name, _expected):
    rows, _ = parse_fixture(name)
    assert all(r.title for r in rows)


@pytest.mark.parametrize("name,_expected", UPSTREAM_FIXTURES)
def test_every_row_has_a_parsed_date(name, _expected):
    rows, _ = parse_fixture(name)
    assert all(r.updated is not None for r in rows)


def test_current_schema_reads_the_format_column():
    rows, _ = parse_fixture("readme-5col-current.md")
    by_title = {r.title: r.format for r in rows}
    assert by_title["Buy Volumes"] == "Coding"
    assert by_title["Customer Package Delivery Report"] == "SQL"
    assert by_title["Design a Web Crawler"] == "System design"
    assert by_title["Design an In-Memory Job Scheduler"] == "Low-level design"
    assert by_title["Build a Refund DAG with Local HTTP Services"] == "AI coding"


def test_format_column_beats_the_route_for_sql_under_problems():
    """SQL and Coding both live under /problems/, so only the column can tell."""
    rows, _ = parse_fixture("readme-5col-current.md")
    sql = [r for r in rows if r.title == "Customer Package Delivery Report"][0]
    assert sql.url.startswith("https://www.fastprep.io/problems/")
    assert sql.format == "SQL"


def test_format_page_hint_beats_the_route():
    rows, report = parse_fixture("formats-sql-4col.md", format_hint="SQL")
    assert {r.format for r in rows} == {"SQL"}
    assert report.warnings == []


def test_format_page_without_a_hint_falls_back_to_the_route():
    # Documented ambiguity: the route says Coding for every /problems/ row.
    rows, _ = parse_fixture("formats-sql-4col.md")
    assert {r.format for r in rows} == {"Coding"}


def test_unknown_format_hint_is_reported_not_swallowed():
    _, report = parse_fixture("formats-sql-4col.md", format_hint="Quantum")
    assert any("Quantum" in w for w in report.warnings)


def test_route_fallback_labels_pre_format_schemas():
    rows, _ = parse_fixture("readme-4col-uploaded-time.md")
    assert all(r.format == "Coding" for r in rows if "/problems/" in (r.url or ""))


def test_gitbook_era_rows_have_no_link_and_no_format():
    rows, _ = parse_fixture("readme-3col-gitbook.md")
    assert all(r.url is None for r in rows)
    assert all(r.format is None for r in rows)


def test_freshness_markers_are_stripped_from_dates():
    rows, _ = parse_fixture("readme-5col-current.md")
    crawler = [r for r in rows if r.title == "Design a Web Crawler"][0]
    assert crawler.updated == date(2026, 8, 16)


def test_decorative_tables_do_not_win_over_the_question_table():
    text = read_fixture("synthetic", "decorative-tables.md")
    rows, report = parse.parse_document(text, "decorative.md")
    assert report.header.startswith("| Company | OA / Interview Question |")
    assert report.rows_parsed == 3


def test_unknown_header_is_fatal():
    text = read_fixture("synthetic", "unknown-header.md")
    with pytest.raises(schemas.UnknownSchemaError) as exc:
        parse.parse_document(text, "unknown-header.md")
    assert "Difficulty" in str(exc.value)


def test_document_without_a_table_is_fatal():
    with pytest.raises(schemas.UnknownSchemaError):
        parse.parse_document("# Just prose\n\nNo table here.\n", "empty.md")


def test_truncated_row_is_skipped_and_recorded():
    """The sync's row-drop guard (D9) can only fire if the loss is recorded."""
    text = read_fixture("synthetic", "truncated.md")
    rows, report = parse.parse_document(text, "truncated.md")
    assert report.rows_parsed == 1
    assert len(report.skipped) == 1
    assert "truncated.md:4" in report.skipped[0]


# --- normalisation ------------------------------------------------------


def test_normalize_keys_by_url_slug(vocab):
    rows, report = parse_fixture("readme-5col-current.md")
    problems = parse.normalize(rows, vocab, TODAY, report)
    keys = {p.key for p in problems.values()}
    assert "problems/amazon-buy-volumes" in keys
    assert "system-design/web-crawler" in keys


def test_normalize_splits_companies_with_the_vocabulary(vocab):
    rows, report = parse_fixture("readme-5col-current.md")
    problems = parse.normalize(rows, vocab, TODAY, report)
    by_title = {p.title: p for p in problems.values()}
    assert by_title["Design an Online Ordering Platform"].companies == [
        "Zomato / Eternal",
        "Amazon",
    ]
    assert by_title["Maximum Production Within Power"].companies == ["Zomato / Eternal"]


def test_unattributed_yields_no_company(vocab):
    rows, report = parse_fixture("readme-5col-current.md")
    problems = parse.normalize(rows, vocab, TODAY, report)
    by_title = {p.title: p for p in problems.values()}
    assert by_title["Design Durable Long-Running Agentic Query Execution"].companies == []


def test_ids_are_stable_under_row_reordering(vocab):
    rows, report = parse_fixture("readme-5col-current.md")
    forward = parse.normalize(rows, vocab, TODAY, report)
    backward = parse.normalize(list(reversed(rows)), vocab, TODAY, report)
    assert set(forward) == set(backward)
    assert {p.key for p in forward.values()} == {p.key for p in backward.values()}


def test_parse_is_idempotent(vocab):
    a_rows, a_rep = parse_fixture("readme-5col-current.md")
    b_rows, b_rep = parse_fixture("readme-5col-current.md")
    a = {k: v.to_dict() for k, v in parse.normalize(a_rows, vocab, TODAY, a_rep).items()}
    b = {k: v.to_dict() for k, v in parse.normalize(b_rows, vocab, TODAY, b_rep).items()}
    assert a == b


def test_first_and_last_seen_are_our_observation_not_upstreams(vocab):
    rows, report = parse_fixture("readme-5col-current.md")
    problems = parse.normalize(rows, vocab, TODAY, report)
    p = [x for x in problems.values() if x.title == "Buy Volumes"][0]
    assert p.first_seen == p.last_seen == "2026-08-20"
    assert p.upstream_updated == "2024-11-23"
    assert p.state == "active"


def test_duplicate_urls_merge_keeping_the_newer_date(vocab):
    """Real upstream shape: one URL under two titles, with different dates."""
    text = (
        "| Company | OA / Interview Question | Format | Practice | Updated |\n"
        "| :-- | :-- | :-- | :-: | :-- |\n"
        "| **Amazon** | [Buy Volumes](https://www.fastprep.io/problems/amazon-buy-volumes)"
        " | Coding | x | Nov 23, 2024 |\n"
        "| **Meta** | [Buy Volume](https://www.fastprep.io/problems/amazon-buy-volumes)"
        " | Coding | x | Aug 12, 2026 |\n"
    )
    rows, report = parse.parse_document(text, "dupes.md")
    problems = parse.normalize(rows, vocab, TODAY, report)
    assert len(problems) == 1
    p = next(iter(problems.values()))
    assert p.title == "Buy Volume"
    assert p.upstream_updated == "2026-08-12"
    assert p.companies == ["Meta", "Amazon"]
    assert any("duplicate id" in w for w in report.warnings)


def test_linkless_rows_do_not_collide(vocab):
    rows, report = parse_fixture("readme-3col-gitbook.md")
    problems = parse.normalize(rows, vocab, TODAY, report)
    assert len(problems) == report.rows_parsed
    assert all(p.key.startswith("untitled:") for p in problems.values())


def test_unknown_company_is_kept_and_warned(vocab):
    rows, report = parse_fixture("formats-sql-4col.md", format_hint="SQL")
    problems = parse.normalize(rows, vocab, TODAY, report)
    names = {c for p in problems.values() for c in p.companies}
    assert "Odoo" in names
    assert any("Odoo" in w for w in report.warnings)
