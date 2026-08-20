"""Abort thresholds (FR-7, D9).

Every guard here answers the same question: is today's parse plausible enough to
commit? A silent zero-row result or a mass "removal" caused by an upstream
refactor would look exactly like real data to everything downstream, so these
checks fail the run loudly instead.
"""

from __future__ import annotations

from .model import Problem

# D9: a drop of more than this fraction of yesterday's rows aborts the sync.
ROW_DROP_LIMIT = 0.10
# D9: divergence between the README and the formats pages warns at any size and
# aborts above max(DIVERGENCE_FLOOR rows, DIVERGENCE_FRACTION). Today it is
# exactly 0, so any drift is signal.
DIVERGENCE_FLOOR = 25
DIVERGENCE_FRACTION = 0.01


class SyncAbort(Exception):
    """Raised when today's parse is too implausible to commit."""


def check_row_count(previous_count: int, current_count: int) -> list[str]:
    """Zero rows is never a valid 'everything was deleted'."""
    if current_count == 0:
        raise SyncAbort(
            "parsed 0 rows. This is always a failure, never a valid result: "
            "upstream has never published an empty table."
        )
    if previous_count == 0:
        return []
    drop = previous_count - current_count
    if drop > 0 and drop / previous_count > ROW_DROP_LIMIT:
        raise SyncAbort(
            f"row count fell from {previous_count} to {current_count} "
            f"({drop / previous_count:.1%}), above the {ROW_DROP_LIMIT:.0%} abort "
            "threshold. Inspect upstream before committing; a parser regression "
            "and a real mass deletion look identical from here."
        )
    return []


def check_divergence(readme_ids: set[str], formats_ids: set[str]) -> list[str]:
    """Cross-check the two upstream sources against each other."""
    only_readme = readme_ids - formats_ids
    only_formats = formats_ids - readme_ids
    diverged = len(only_readme) + len(only_formats)
    if diverged == 0:
        return []

    limit = max(DIVERGENCE_FLOOR, int(max(len(readme_ids), len(formats_ids)) * DIVERGENCE_FRACTION))
    detail = (
        f"{diverged} rows diverge between README and formats pages "
        f"({len(only_readme)} README-only, {len(only_formats)} formats-only)"
    )
    if diverged > limit:
        raise SyncAbort(f"{detail}, above the abort threshold of {limit}.")
    return [f"{detail}; below the abort threshold of {limit}."]


def check_unclassified(problems: dict[str, Problem]) -> list[str]:
    """Every live row must carry a format.

    Mirrors upstream's own `unclassified row` guard. Tombstones are exempt:
    the pre-2026 layouts they came from had no format column at all, and
    re-litigating history is not what this check is for.
    """
    unclassified = sorted(
        pid for pid, p in problems.items() if p.state != "removed" and not p.format
    )
    if unclassified:
        sample = ", ".join(unclassified[:5])
        raise SyncAbort(
            f"{len(unclassified)} live rows have no format (e.g. {sample}). "
            "Either upstream added a format label we do not know, or the format "
            "column moved."
        )
    return []
