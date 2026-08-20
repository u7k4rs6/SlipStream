"""Table extraction and cell cleaning — the layer that knows pipes, not meaning."""

from __future__ import annotations

from slipstream import mdtable

from conftest import read_fixture


def test_finds_every_table_in_order():
    tables = mdtable.find_tables(read_fixture("synthetic", "decorative-tables.md"))
    assert [len(t.rows) for t in tables] == [2, 3]
    assert tables[1].header.startswith("| Company | OA / Interview Question |")


def test_header_line_no_points_at_the_header():
    text = read_fixture("synthetic", "decorative-tables.md")
    table = mdtable.find_tables(text)[1]
    lines = text.split("\n")
    assert lines[table.header_line_no - 1].strip() == table.header


def test_escaped_pipe_does_not_create_a_phantom_column():
    cells = mdtable.split_row(r"| Stripe | Ledger Reconciliation \| Batch Mode | Coding |")
    assert cells == ("Stripe", "Ledger Reconciliation | Batch Mode", "Coding")


def test_escaped_pipe_row_keeps_its_column_count(vocab):
    table = mdtable.find_tables(read_fixture("synthetic", "decorative-tables.md"))[1]
    stripe = [r for r in table.rows if r[0] == "**Stripe**"][0]
    assert len(stripe) == 5


def test_clean_company_strips_favicons_and_bold():
    cell = '<img src="https://x/amazon.png" width="16"> **Amazon**'
    assert mdtable.clean_company(cell) == "Amazon"


def test_clean_company_keeps_slash_joined_names_intact():
    assert mdtable.clean_company("**Zomato / Eternal / Amazon**") == "Zomato / Eternal / Amazon"


def test_extract_link_skips_the_practice_badge():
    cell = "[![Practice][p]](https://www.fastprep.io/problems/amazon-buy-volumes)"
    text, url = mdtable.extract_link(cell)
    # The only link is an image badge, so there is no *content* link to take.
    assert (text, url) == (None, None)


def test_extract_link_takes_the_question_link():
    cell = "[Buy Volumes](https://www.fastprep.io/problems/amazon-buy-volumes)"
    assert mdtable.extract_link(cell) == (
        "Buy Volumes",
        "https://www.fastprep.io/problems/amazon-buy-volumes",
    )


def test_extract_link_falls_back_to_html_anchors():
    cell = '<a href="https://fastprep.gitbook.io/oa/amazon-buy-volumes">Buy Volumes</a>'
    text, url = mdtable.extract_link(cell)
    assert url == "https://fastprep.gitbook.io/oa/amazon-buy-volumes"
    assert text == "Buy Volumes"


def test_extract_link_on_plain_text_returns_text_only():
    assert mdtable.extract_link("Get Mean Rank Count") == ("Get Mean Rank Count", None)
