"""Company vocabulary — the `Zomato / Eternal` problem."""

from __future__ import annotations

from slipstream import companies

from conftest import read_fixture


def test_vocabulary_loads_from_upstream_domains_json(vocab):
    assert "Amazon" in vocab
    assert "Zomato / Eternal" in vocab
    assert len(vocab) > 10


def test_slash_containing_name_stays_one_company(vocab):
    names, unknown = vocab.split_cell("Zomato / Eternal")
    assert names == ["Zomato / Eternal"]
    assert unknown == []


def test_longest_match_wins_over_its_prefix(vocab):
    names, unknown = vocab.split_cell("Zomato / Eternal / Amazon")
    assert names == ["Zomato / Eternal", "Amazon"]
    assert unknown == []


def test_plain_multi_company_cell_splits(vocab):
    names, _ = vocab.split_cell("DoorDash / Robinhood / Snowflake / Postman / Figma")
    assert names == ["DoorDash", "Robinhood", "Snowflake", "Postman", "Figma"]


def test_unattributed_is_not_a_company(vocab):
    assert vocab.split_cell("Unattributed") == ([], [])


def test_empty_cell_yields_nothing(vocab):
    assert vocab.split_cell("   ") == ([], [])


def test_unknown_company_is_kept_but_reported(vocab):
    names, unknown = vocab.split_cell("Amazon / Cerebras")
    assert names == ["Amazon", "Cerebras"]
    assert unknown == ["Cerebras"]


def test_casing_variants_canonicalise_to_the_brand_spelling(vocab):
    names, _ = vocab.split_cell("infosys")
    assert names == ["Infosys"]


def test_authoritative_source_wins_over_readme_spelling():
    v = companies.from_sources(
        domains_json='{"MathWorks": "mathworks.com"}',
        extra=["Mathworks"],
    )
    assert v.split_cell("Mathworks")[0] == ["MathWorks"]


def test_readme_curated_list_is_parsed():
    readme = read_fixture("synthetic", "readme-company-list.md")
    v = companies.from_sources(readme_text=readme)
    assert "Goldman Sachs" in v
    assert "Zomato / Eternal" in v
    assert "Amazon" in v


def test_malformed_domains_json_does_not_crash():
    v = companies.from_sources(domains_json="{not json")
    assert len(v) == 0
