"""Markdown table extraction and cell cleaning.

Kept deliberately separate from schema knowledge: this module only knows how to
find a pipe table and split it into cells. What the cells *mean* is schemas.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DIVIDER = re.compile(r"^\|[\s:\-|]+\|$")
_HTML_TAG = re.compile(r"<[^>]+>")
# The text group must tolerate one level of nesting: upstream's practice badge is
# ``[![Practice][p]](url)``, whose link text is itself a bracketed image reference.
_MD_LINK = re.compile(
    r"\[(?P<text>(?:[^\[\]]|\[[^\[\]]*\])*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
)
_HTML_LINK = re.compile(r"<a\s+[^>]*href=[\"'](?P<url>[^\"']+)[\"'][^>]*>", re.I)
_IMAGE_LINK = re.compile(r"^!\[")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


@dataclass(frozen=True)
class Table:
    header: str
    divider: str
    rows: tuple[tuple[str, ...], ...]
    header_line_no: int
    raw_rows: tuple[str, ...]


def split_row(line: str) -> tuple[str, ...]:
    """Split a pipe-table row into stripped cells.

    Splits on unescaped pipes only, so a literal ``\\|`` inside a cell does not
    create a phantom column.
    """
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    parts = re.split(r"(?<!\\)\|", body)
    return tuple(p.strip().replace("\\|", "|") for p in parts)


def find_tables(text: str) -> list[Table]:
    """Return every pipe table in the document, in order.

    A table is a header line, a divider line, then consecutive pipe rows.
    """
    lines = text.split("\n")
    tables: list[Table] = []
    i = 0
    while i < len(lines) - 1:
        line, nxt = lines[i], lines[i + 1]
        if line.startswith("|") and _DIVIDER.match(nxt.strip()):
            rows: list[tuple[str, ...]] = []
            raw: list[str] = []
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                raw.append(lines[j])
                rows.append(split_row(lines[j]))
                j += 1
            tables.append(
                Table(
                    header=line.strip(),
                    divider=nxt.strip(),
                    rows=tuple(rows),
                    header_line_no=i + 1,
                    raw_rows=tuple(raw),
                )
            )
            i = j
        else:
            i += 1
    return tables


def strip_html(cell: str) -> str:
    """Remove HTML tags. Upstream prefixed company cells with favicon <img> tags
    for part of 2026-07, and used <a><img></a> practice buttons before that."""
    return _HTML_TAG.sub("", cell).strip()


def clean_company(cell: str) -> str:
    """Company cell -> plain text.

    Handles: favicon <img> prefixes, bold wrapping, stray markdown.
    """
    text = strip_html(cell)
    text = _BOLD.sub(r"\1", text)
    return " ".join(text.replace("*", " ").split()).strip()


def extract_link(cell: str) -> tuple[str | None, str | None]:
    """Return ``(text, url)`` for the first *content* link in a cell.

    Image links (``[![Practice][p]](url)``) are skipped: upstream's practice
    column is a badge whose URL always duplicates the question URL, so it
    carries no information. Falls back to HTML anchors, used pre-2026.
    """
    for m in _MD_LINK.finditer(cell):
        text = m.group("text")
        if _IMAGE_LINK.match(text.strip()):
            continue
        url = m.group("url").strip()
        if url.startswith("#") or not url:
            continue
        return strip_html(text).strip(), url
    m = _HTML_LINK.search(cell)
    if m:
        return strip_html(_MD_LINK.sub("", cell)).strip() or None, m.group("url").strip()
    # Any link left in the cell is an image badge (content links returned above),
    # so drop the markdown rather than leaking "[![Practice][p]](...)" as a title.
    plain = strip_html(_MD_LINK.sub("", cell)).strip()
    plain = " ".join(plain.split())
    return (plain or None), None
