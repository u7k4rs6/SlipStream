"""Turn upstream markdown into RawRows, then into normalized Problems."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import mdtable, model
from .companies import CompanyVocabulary
from .schemas import (
    COMPANY,
    COMPANY_AND_QUESTION,
    FORMAT,
    KNOWN_FORMATS,
    QUESTION,
    ROUTE_FORMATS,
    UPDATED,
    UnknownSchemaError,
    roles_for,
)


@dataclass
class ParseReport:
    source: str
    header: str = ""
    rows_seen: int = 0
    rows_parsed: int = 0
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    merged_rows: int = 0        # same problem seen in more than one source

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)


def parse_document(
    text: str, source: str, format_hint: str | None = None
) -> tuple[list[model.RawRow], ParseReport]:
    """Parse the question table out of one upstream markdown document.

    ``format_hint`` names the format the whole document is about. The
    ``formats/*.md`` pages carry no Format column -- the page *is* the format --
    and the route prefix cannot recover it, because SQL and Coding questions
    both live under ``/problems/``. Pass "SQL" when parsing ``formats/sql.md``
    or every row on that page is labelled Coding.

    Raises UnknownSchemaError if the document contains no table whose header we
    recognise. That is intentional: yielding zero rows on an unknown header is
    the silent failure this project exists to prevent.
    """
    report = ParseReport(source=source)
    if format_hint and format_hint not in KNOWN_FORMATS:
        report.warn(f"unknown format hint {format_hint!r} (kept verbatim)")
    tables = mdtable.find_tables(text)
    if not tables:
        raise UnknownSchemaError(f"{source}: no markdown table found")

    # The question table is the recognised table with the most rows; upstream
    # pages also contain small decorative tables ("How it works").
    candidates = []
    unknown_headers = []
    for table in tables:
        try:
            roles = roles_for(table.header)
        except UnknownSchemaError:
            unknown_headers.append(table.header)
            continue
        candidates.append((table, roles))

    if not candidates:
        raise UnknownSchemaError(
            f"{source}: no recognised table header. Saw: "
            + "; ".join(repr(h) for h in unknown_headers[:5])
        )

    table, roles = max(candidates, key=lambda tr: len(tr[0].rows))
    report.header = table.header
    report.rows_seen = len(table.rows)

    if len(roles) != len(mdtable.split_row(table.header)):
        report.warn(
            f"header column count {len(mdtable.split_row(table.header))} does not "
            f"match registered roles {len(roles)}"
        )

    rows: list[model.RawRow] = []
    for offset, cells in enumerate(table.rows):
        line_no = table.header_line_no + 2 + offset
        row = _row_from_cells(cells, roles, source, line_no, report, format_hint)
        if row is not None:
            rows.append(row)
    report.rows_parsed = len(rows)
    return rows, report


def _row_from_cells(
    cells, roles, source, line_no, report, format_hint=None
) -> model.RawRow | None:
    if len(cells) != len(roles):
        report.skipped.append(f"{source}:{line_no} expected {len(roles)} cells, got {len(cells)}")
        return None

    by_role = dict(zip(roles, cells))

    if COMPANY_AND_QUESTION in by_role:
        # 2023 two-column layout: no separable title, no link. Unusable.
        report.skipped.append(f"{source}:{line_no} two-column legacy layout has no question column")
        return None

    company_cell = mdtable.clean_company(by_role.get(COMPANY, ""))
    title, url = mdtable.extract_link(by_role.get(QUESTION, ""))
    if title:
        title = " ".join(title.split())
    if not title:
        report.skipped.append(f"{source}:{line_no} no question title")
        return None

    fmt = None
    if FORMAT in by_role:
        fmt = mdtable.strip_html(by_role[FORMAT]).strip() or None
        if fmt and fmt not in KNOWN_FORMATS:
            report.warn(f"unknown format label {fmt!r} (kept verbatim)")
    elif format_hint:
        # A format page states its own format; trust it over the route.
        fmt = format_hint
    elif url:
        # Pre-2026-07-31 schemas carry no format column and no page-level hint.
        # Route prefix is the only signal left, and it cannot distinguish SQL
        # from Coding -- both live under /problems/ -- so this is a fallback,
        # never authoritative.
        key = model.derive_key(url) or ""
        fmt = ROUTE_FORMATS.get(key.split("/")[0])

    return model.RawRow(
        company_cell=company_cell,
        title=title,
        url=url,
        format=fmt,
        updated=model.parse_updated(by_role.get(UPDATED, "")),
        source=source,
        line_no=line_no,
    )


def normalize(
    rows: list[model.RawRow],
    vocab: CompanyVocabulary,
    today: date,
    report: ParseReport | None = None,
) -> dict[str, model.Problem]:
    """Collapse RawRows into Problems keyed by derived ID.

    Duplicate rows are real upstream data -- 12 rows currently share 6 URLs, of
    which 6 are byte-identical and 6 are the same URL under two different titles.
    We keep the entry whose upstream date is newest and record the collision.
    """
    out: dict[str, model.Problem] = {}
    iso = today.isoformat()

    for row in rows:
        companies, unknown = vocab.split_cell(row.company_cell)
        if unknown and report is not None:
            for name in unknown:
                report.warn(f"company not in vocabulary: {name!r}")

        key = model.derive_key(row.url) if row.url else None
        if not key:
            key = model.fallback_key(row.title or "", companies)
        pid = model.derive_id(key)

        candidate = model.Problem(
            id=pid,
            key=key,
            title=row.title or "",
            url=row.url,
            companies=companies,
            format=row.format,
            upstream_updated=row.updated.isoformat() if row.updated else None,
            first_seen=iso,
            last_seen=iso,
            sources=[row.source],
        )

        existing = out.get(pid)
        if existing is None:
            out[pid] = candidate
            continue

        if report is not None:
            report.merged_rows += 1
            # Only *conflicting* duplicates are warned about. Every row legitimately
            # appears twice -- once in README, once on its formats page -- so
            # warning on each would bury the handful of real collisions under two
            # thousand lines of noise and make meta.json useless.
            if existing.title != candidate.title:
                report.warn(
                    f"same URL under two titles: {key!r} "
                    f"({existing.title!r} / {candidate.title!r})"
                )
            elif (
                existing.format
                and candidate.format
                and existing.format != candidate.format
            ):
                report.warn(
                    f"sources disagree on format for {key!r}: "
                    f"{existing.format!r} / {candidate.format!r}"
                )
        out[pid] = _merge_duplicate(existing, candidate)

    return out


def _merge_duplicate(a: model.Problem, b: model.Problem) -> model.Problem:
    """Prefer the newer upstream date; union companies and sources.

    On an equal date -- which is the normal case, since the same row is being
    seen twice through two sources -- the *first* entry wins. fetch.SOURCES puts
    README first deliberately: its Format column is the authoritative label,
    while a formats page can only assert the format its whole page is about.
    """
    newer, older = (a, b)
    if (b.upstream_updated or "") > (a.upstream_updated or ""):
        newer, older = (b, a)
    merged = model.Problem.from_dict(newer.to_dict())
    for c in older.companies:
        if c not in merged.companies:
            merged.companies.append(c)
    for s in older.sources:
        if s not in merged.sources:
            merged.sources.append(s)
    merged.format = merged.format or older.format
    return merged
