"""Normalized problem records and stable ID derivation.

Upstream publishes no per-problem identifier, and its row order changes on every
sync (rows are re-sorted newest-first), so position is meaningless as identity.

Measured over upstream's git history, the URL slug is a strong key: 1,236 of
1,293 slugs survived the largest observed monthly churn, and crucially *titles
change underneath stable slugs* -- which is precisely the case that would orphan
title-keyed personal data.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import date
from urllib.parse import urlsplit

ID_LENGTH = 12

# Two date shapes appear in upstream history: "Sep 17, 2024" (current) and
# "Aug, 31, 2023" (2023-2024, extra comma after the month).
_DATE = re.compile(
    r"(?P<mon>[A-Z][a-z]{2}),?\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})"
)
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    )
}
# Freshness markers are DERIVED by upstream from the date itself (fire <= 14
# days, new <= 45). They carry no independent information, so we strip them and
# recompute client-side.
_MARKERS = ("\U0001f525", "\U0001f195")


def parse_updated(cell: str) -> date | None:
    m = _DATE.search(strip_markers(cell))
    if not m:
        return None
    month = _MONTHS.get(m.group("mon"))
    if not month:
        return None
    try:
        return date(int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None


def strip_markers(cell: str) -> str:
    out = cell
    for mark in _MARKERS:
        out = out.replace(mark, "")
    return " ".join(out.split()).strip()


def derive_key(url: str) -> str | None:
    """Human-readable stable key: ``<namespace>/<slug>`` from the URL path.

    For every current upstream link the path is exactly two segments
    (``/problems/amazon-buy-volumes``), so this is the full path. For deeper
    historical paths it takes first and last segments, which stays stable when
    intermediate segments are reorganised.
    """
    if not url:
        return None
    path = urlsplit(url).path.strip("/")
    if not path:
        return None
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None
    if len(segments) == 1:
        return segments[0].lower()
    return f"{segments[0].lower()}/{segments[-1].lower()}"


def derive_id(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:ID_LENGTH]


def fallback_key(title: str, companies: list[str]) -> str:
    """Key for rows that have no link at all (upstream's 2023 layouts).

    Only reachable via historical fixtures; current upstream links every row.
    Prefixed so it can never collide with a URL-derived key.
    """
    base = " ".join(title.split()).casefold()
    who = "+".join(sorted(c.casefold() for c in companies))
    return f"untitled:{who}:{base}"


@dataclass
class Problem:
    id: str
    key: str
    title: str
    url: str | None
    companies: list[str]
    format: str | None
    upstream_updated: str | None      # ISO date
    first_seen: str                   # ISO date, OUR observation
    last_seen: str                    # ISO date
    state: str = "active"             # active | removed
    removed_on: str | None = None
    aliases: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Problem":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class RawRow:
    """A single parsed table row, before normalisation."""

    company_cell: str
    title: str | None
    url: str | None
    format: str | None
    updated: date | None
    source: str
    line_no: int
