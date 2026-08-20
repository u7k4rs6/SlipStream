"""Known upstream table schemas.

Upstream has changed its README table header ten times in three years, four of
those in the six weeks before this project started. Rather than pin to one
header, we register every header we have ever observed and map its columns onto
semantic roles. An unregistered header is a hard error: it must fail loudly in
CI rather than silently yield zero rows.
"""

from __future__ import annotations

# Semantic roles a column can carry.
COMPANY = "company"
QUESTION = "question"
FORMAT = "format"
PRACTICE = "practice"
UPDATED = "updated"
COMPANY_AND_QUESTION = "company_and_question"  # 2023 two-column layout

# header line -> column roles, in order.
#
# Each entry is a real header observed in upstream git history. The date is when
# it first appeared. Keep this list append-only; deleting an entry would make old
# fixtures fail for the wrong reason.
KNOWN_SCHEMAS: dict[str, tuple[str, ...]] = {
    # 2023-09-04 — two columns, no links at all.
    "| Company OA | Last Updated Time |": (COMPANY_AND_QUESTION, UPDATED),
    # 2023-09-04 — three columns, still no links.
    "| Company | OA Question | Last Updated Time |": (COMPANY, QUESTION, UPDATED),
    # 2023-11-13 — practice column added; links point at fastprep.gitbook.io.
    "| Company | OA Question | Practice (Beta) | Last Updated Time |": (
        COMPANY, QUESTION, PRACTICE, UPDATED,
    ),
    # 2024-09-26 — "Uploaded Time".
    "| Company | OA Question | Practice (Beta) | Uploaded Time |": (
        COMPANY, QUESTION, PRACTICE, UPDATED,
    ),
    # 2025-03-23 — "Updated Time".
    "| Company | OA Question | Practice (Beta) | Updated Time |": (
        COMPANY, QUESTION, PRACTICE, UPDATED,
    ),
    # 2026-07-09 — beta dropped from the practice column.
    "| Company | OA Question | Practice | Updated Time |": (
        COMPANY, QUESTION, PRACTICE, UPDATED,
    ),
    "| Company | OA Question | Practice | Updated |": (
        COMPANY, QUESTION, PRACTICE, UPDATED,
    ),
    # 2026-07-27 — question column renamed; favicon <img> appears in company cell.
    "| Company | OA / Interview Question | Practice | Updated |": (
        COMPANY, QUESTION, PRACTICE, UPDATED,
    ),
    # 2026-07-31 — format column introduced, briefly called "Practice format".
    "| Company | OA / Interview Question | Practice format | Practice | Updated |": (
        COMPANY, QUESTION, FORMAT, PRACTICE, UPDATED,
    ),
    # 2026-07-31 — current schema.
    "| Company | OA / Interview Question | Format | Practice | Updated |": (
        COMPANY, QUESTION, FORMAT, PRACTICE, UPDATED,
    ),
}

# Format labels upstream uses. Anything outside this set is reported, never
# silently coerced, because a new format is a signal worth seeing.
KNOWN_FORMATS = frozenset(
    {"Coding", "SQL", "System design", "Low-level design", "AI coding"}
)

# Route prefix -> format. Used ONLY as a fallback when the table has no format
# column (every schema before 2026-07-31). It cannot be used as the primary
# source: SQL and Coding rows both live under /problems/, so the route is
# genuinely ambiguous for those two.
ROUTE_FORMATS = {
    "problems": "Coding",
    "system-design": "System design",
    "low-level-design": "Low-level design",
    "project-coding": "AI coding",
}

# Sentinel company meaning "no source-backed employer was reported".
UNATTRIBUTED = "Unattributed"


class UnknownSchemaError(Exception):
    """Raised when a table header is not in KNOWN_SCHEMAS.

    This is deliberately fatal. Silently returning zero rows on an unrecognised
    header is the exact failure this project exists to prevent.
    """


def roles_for(header: str) -> tuple[str, ...]:
    try:
        return KNOWN_SCHEMAS[header]
    except KeyError:
        raise UnknownSchemaError(
            f"Unrecognised upstream table header:\n  {header!r}\n"
            "Upstream has changed its schema. Add the new header to "
            "KNOWN_SCHEMAS in schemas.py, add a fixture for it, and confirm the "
            "column roles before trusting any parsed output."
        ) from None
