"""Classify what moved between two syncs.

The whole point of slug-derived IDs (model.py) is that personal data survives
upstream churn. This module is where that promise is kept or broken: it decides
which of today's rows are *the same problem* as yesterday's, and a wrong answer
either orphans personal work or attaches it to someone else's question.

So the rules here are deliberately conservative. A relink is auto-merged only on
an exact, unambiguous ``(title, companies, format)`` match (D10); anything less
certain is reported for manual confirmation rather than guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .model import Problem

ADDED = "added"
REMOVED = "removed"
RETITLED = "retitled"
RELINKED = "relinked"
RECOMPANIED = "recompanied"

KINDS = (ADDED, REMOVED, RETITLED, RELINKED, RECOMPANIED)

# D7: a tombstone with no personal data attached ages out of the hot dataset
# after this long. It stays in archive.json forever regardless.
TOMBSTONE_RETENTION_DAYS = 180


@dataclass(frozen=True)
class Change:
    kind: str
    id: str
    key: str
    title: str
    before: dict | None = None
    after: dict | None = None
    previous_id: str | None = None   # relinked: the ID this row used to have
    previous_key: str | None = None

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "id": self.id, "key": self.key, "title": self.title}
        if self.before is not None:
            out["before"] = self.before
        if self.after is not None:
            out["after"] = self.after
        if self.previous_id is not None:
            out["previous_id"] = self.previous_id
            out["previous_key"] = self.previous_key
        return out


@dataclass(frozen=True)
class AmbiguousRelink:
    """A removed/added pair that looks like a relink but is not provably one.

    Surfaced in the What's-new view for manual confirmation. Never auto-merged:
    silently merging the wrong pair corrupts personal data, which is the one
    failure this design exists to prevent (D10).
    """

    added_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]
    title: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "added_ids": list(self.added_ids),
            "removed_ids": list(self.removed_ids),
            "title": self.title,
            "reason": self.reason,
        }


@dataclass
class DiffResult:
    date: str
    problems: dict[str, Problem] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    ambiguous_relinks: list[AmbiguousRelink] = field(default_factory=list)
    archived: list[Problem] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts = {kind: 0 for kind in KINDS}
        for change in self.changes:
            counts[change.kind] += 1
        return counts

    def of_kind(self, kind: str) -> list[Change]:
        return [c for c in self.changes if c.kind == kind]

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "counts": self.counts,
            "changes": [c.to_dict() for c in self.changes],
            "ambiguous_relinks": [a.to_dict() for a in self.ambiguous_relinks],
        }


def _signature(p: Problem) -> tuple:
    """The identity a relink must match exactly (D10).

    Companies compare as a *set*: their order follows the upstream cell, which
    is not semantic, so a reordering must not defeat an otherwise exact match.
    """
    return (p.title, frozenset(p.companies), p.format)


def diff(
    previous: dict[str, Problem],
    current: dict[str, Problem],
    today: date,
) -> DiffResult:
    """Compare yesterday's dataset against today's.

    ``previous`` is the full committed dataset including tombstones; ``current``
    is what upstream shows today (parse.normalize output). Returns the merged
    next state plus the classified changes.
    """
    iso = today.isoformat()
    result = DiffResult(date=iso)

    live_before = {pid for pid, p in previous.items() if p.state != "removed"}
    added_ids = set(current) - live_before
    removed_ids = live_before - set(current)

    relinks, ambiguous = _match_relinks(previous, current, added_ids, removed_ids)
    result.ambiguous_relinks = ambiguous
    relinked_new = {new for new, _ in relinks.items()}
    relinked_old = set(relinks.values())

    for pid, now in current.items():
        was = previous.get(pid)
        if pid in relinked_new:
            old = previous[relinks[pid]]
            result.problems[pid] = _carry_forward(old, now, iso, alias_of=old)
            result.changes.append(
                Change(
                    kind=RELINKED,
                    id=pid,
                    key=now.key,
                    title=now.title,
                    before={"url": old.url, "key": old.key},
                    after={"url": now.url, "key": now.key},
                    previous_id=old.id,
                    previous_key=old.key,
                )
            )
            result.archived.append(_tombstone(old, iso, superseded_by=pid))
        elif was is None or was.state == "removed":
            # Absent yesterday, or tombstoned and now back. Either way it is new
            # to the live dataset; a resurrected row keeps its original
            # first_seen so "date added" does not lie.
            result.problems[pid] = (
                _carry_forward(was, now, iso) if was is not None else _fresh(now, iso)
            )
            result.changes.append(
                Change(kind=ADDED, id=pid, key=now.key, title=now.title)
            )
        else:
            result.problems[pid] = _carry_forward(was, now, iso)
            result.changes.extend(_field_changes(was, now))

    for pid in removed_ids:
        if pid in relinked_old:
            continue
        was = previous[pid]
        stone = _tombstone(was, iso)
        result.problems[pid] = stone
        result.archived.append(stone)
        result.changes.append(
            Change(kind=REMOVED, id=pid, key=was.key, title=was.title)
        )

    # Tombstones that predate this run are carried through untouched. A
    # relinked-away ID is deliberately not among them: it lives on as an alias
    # on its successor, and re-adding it here would show the same problem twice.
    for pid, was in previous.items():
        if pid in relinked_old:
            continue
        result.problems.setdefault(pid, was)

    result.changes.sort(key=lambda c: (KINDS.index(c.kind), c.key, c.id))
    return result


def _match_relinks(previous, current, added_ids, removed_ids):
    """Pair added IDs with removed ones by exact signature.

    A pair is auto-merged only when the signature maps to exactly one added and
    one removed row. Many-to-one in either direction is ambiguous and is
    reported instead (D10).
    """
    by_sig_added: dict[tuple, list[str]] = {}
    for pid in added_ids:
        by_sig_added.setdefault(_signature(current[pid]), []).append(pid)
    by_sig_removed: dict[tuple, list[str]] = {}
    for pid in removed_ids:
        by_sig_removed.setdefault(_signature(previous[pid]), []).append(pid)

    relinks: dict[str, str] = {}
    ambiguous: list[AmbiguousRelink] = []
    for sig, new_ids in by_sig_added.items():
        old_ids = by_sig_removed.get(sig)
        if not old_ids:
            continue
        if len(new_ids) == 1 and len(old_ids) == 1:
            relinks[new_ids[0]] = old_ids[0]
            continue
        ambiguous.append(
            AmbiguousRelink(
                added_ids=tuple(sorted(new_ids)),
                removed_ids=tuple(sorted(old_ids)),
                title=sig[0],
                reason=(
                    f"{len(new_ids)} added and {len(old_ids)} removed rows share the "
                    "same (title, companies, format); no unambiguous pairing"
                ),
            )
        )
    ambiguous.sort(key=lambda a: (a.title, a.added_ids))
    return relinks, ambiguous


def _field_changes(was: Problem, now: Problem) -> list[Change]:
    changes = []
    if was.title != now.title:
        changes.append(
            Change(
                kind=RETITLED,
                id=now.id,
                key=now.key,
                title=now.title,
                before={"title": was.title},
                after={"title": now.title},
            )
        )
    if set(was.companies) != set(now.companies):
        changes.append(
            Change(
                kind=RECOMPANIED,
                id=now.id,
                key=now.key,
                title=now.title,
                before={"companies": list(was.companies)},
                after={"companies": list(now.companies)},
            )
        )
    return changes


def _fresh(now: Problem, iso: str) -> Problem:
    p = Problem.from_dict(now.to_dict())
    p.first_seen = iso
    p.last_seen = iso
    p.state = "active"
    p.removed_on = None
    return p


def _carry_forward(
    was: Problem, now: Problem, iso: str, alias_of: Problem | None = None
) -> Problem:
    """Today's upstream values, but *our* observation history is preserved."""
    p = Problem.from_dict(now.to_dict())
    p.first_seen = was.first_seen
    p.last_seen = iso
    p.state = "active"
    p.removed_on = None
    p.aliases = list(was.aliases)
    if alias_of is not None:
        # Personal data is keyed by derived ID (FR-4), so the alias that has to
        # survive a relink is the *old ID*, not the old slug.
        for old_id in [*was.aliases, alias_of.id]:
            if old_id not in p.aliases:
                p.aliases.append(old_id)
    return p


def _tombstone(was: Problem, iso: str, superseded_by: str | None = None) -> Problem:
    p = Problem.from_dict(was.to_dict())
    p.state = "removed"
    p.removed_on = iso
    if superseded_by and superseded_by not in p.aliases:
        p.aliases.append(superseded_by)
    return p


def prune_tombstones(
    problems: dict[str, Problem],
    today: date,
    referenced_ids: set[str] | None = None,
    retention_days: int = TOMBSTONE_RETENTION_DAYS,
) -> tuple[dict[str, Problem], list[Problem]]:
    """Drop aged-out tombstones from the hot dataset (D7).

    ``referenced_ids`` is the set of IDs the personal layer points at. Passing
    ``None`` means "unknown", and then **nothing is pruned**: the sync job holds
    no credential for the private personal repo (D2), so in the normal daily run
    it cannot prove a tombstone is unreferenced -- and dropping one that is
    referenced orphans real work. Keeping a stale row is cheap; losing personal
    data is not.

    Returns ``(kept, dropped)``. Dropped rows are already in archive.json.
    """
    if referenced_ids is None:
        return dict(problems), []

    cutoff = (today - timedelta(days=retention_days)).isoformat()
    kept: dict[str, Problem] = {}
    dropped: list[Problem] = []
    for pid, p in problems.items():
        if (
            p.state == "removed"
            and pid not in referenced_ids
            and (p.removed_on or "") < cutoff
        ):
            dropped.append(p)
        else:
            kept[pid] = p
    return kept, dropped
