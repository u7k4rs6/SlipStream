from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
UPSTREAM = FIXTURES / "upstream"
SYNTHETIC = FIXTURES / "synthetic"


def read_fixture(*parts: str) -> str:
    return (FIXTURES.joinpath(*parts)).read_text(encoding="utf-8")


@pytest.fixture
def current_readme() -> str:
    return read_fixture("upstream", "readme-5col-current.md")


@pytest.fixture
def vocab():
    from slipstream import companies

    return companies.from_sources(
        domains_json=read_fixture("synthetic", "company-domains.json")
    )
