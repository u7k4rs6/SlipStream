"""Write the artifacts the frontend and the changelog read.

Two properties matter more than anything else here:

*Determinism.* The same dataset must produce byte-identical files, or the daily
job commits noise every morning and "what changed today" becomes unreadable.
Everything is sorted by a content-derived key, never by upstream row order --
upstream re-sorts its table newest-first on every sync.

*Reviewable diffs.* ``problems.json`` is written one record per line, so a git
diff shows the rows that actually moved rather than one 400 KB line.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .diff import DiffResult, KINDS, RECOMPANIED, RELINKED, REMOVED, RETITLED
from .model import Problem

SCHEMA_VERSION = 1

# Fields that move on every run without carrying new information. Every live row
# shares the same `last_seen` -- by definition it is the current sync -- so
# advancing it daily would rewrite all ~1,900 rows every morning and commit a
# 120 KB diff saying nothing. Rewriting is skipped when these are the only
# difference, which is what makes an unchanged upstream a true no-op (arch §6).
# The cost: on a quiet day `last_seen` lags, and meta.json's `synced_at` is the
# authority on when the sync actually last ran.
VOLATILE_FIELDS = ("last_seen",)


class EmitError(Exception):
    """Raised when an existing artifact cannot be safely extended."""

# Search index (frontend-spec §5): prefixes are emitted for tokens this long or
# longer, so as-you-type matching starts at the third keystroke.
MIN_PREFIX = 3

_WORD = re.compile(r"[a-z0-9]+")

CHANGELOG_TITLE = "# Changelog"
# The changelog is for reading. The bootstrap run legitimately "adds" ~1,900
# rows, and listing them all produces a 100 KB entry nobody scrolls through, so
# long lists are truncated with a pointer to the complete machine-readable file.
CHANGELOG_MAX_PER_KIND = 50
_SECTION = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$", re.M)

_KIND_HEADINGS = {
    "added": "Added",
    "removed": "Removed",
    "retitled": "Retitled",
    "relinked": "Relinked",
    "recompanied": "Company changed",
}


@dataclass
class Meta:
    """What `data/meta.json` records instead of a verbatim mirror (D8).

    ``git show <upstream_sha>:README.md`` against upstream reconstructs the exact
    input, so the sync stays reproducible without committing ~440 KB of
    unlicensed third-party text on every change.
    """

    upstream_sha: str
    synced_at: str                                  # ISO 8601, supplied by caller
    sources: dict[str, str] = field(default_factory=dict)   # path -> sha256
    warnings: list[str] = field(default_factory=list)

    def to_dict(self, problems: dict[str, Problem], result: DiffResult | None) -> dict:
        live = sum(1 for p in problems.values() if p.state != "removed")
        doc = {
            "schema_version": SCHEMA_VERSION,
            "upstream_sha": self.upstream_sha,
            "synced_at": self.synced_at,
            "sources": dict(sorted(self.sources.items())),
            "counts": {
                "live": live,
                "tombstoned": len(problems) - live,
                "total": len(problems),
            },
            "warnings": list(self.warnings),
        }
        if result is not None:
            doc["last_change_date"] = result.date
            doc["changes"] = result.counts
            doc["ambiguous_relinks"] = len(result.ambiguous_relinks)
        return doc


@dataclass
class EmitReport:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    dataset_changed: bool = False

    def __str__(self) -> str:
        return (
            f"{len(self.written)} written, {len(self.unchanged)} unchanged, "
            f"dataset_changed={self.dataset_changed}"
        )


def source_digest(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def ordered(problems: dict[str, Problem]) -> list[Problem]:
    """Rows in a stable, content-derived order.

    Sorted by key rather than by date: a date change would otherwise reshuffle
    the whole file and bury the real diff.
    """
    return sorted(problems.values(), key=lambda p: (p.key, p.id))


def tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def problems_document(problems: dict[str, Problem]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "count": len(problems),
        "problems": [p.to_dict() for p in ordered(problems)],
    }


def search_index(problems: dict[str, Problem]) -> dict:
    """Inverted index over title + companies (frontend-spec §5).

    Postings are row positions in ``problems.json``, in the same order
    ``ordered()`` produces -- the two files are only meaningful together, so
    they are always written in the same run.

    The prefix map points at *tokens*, not postings: mapping every prefix
    straight to its rows would multiply the index by average token length for no
    added capability, since the client can union the postings itself.
    """
    tokens: dict[str, set[int]] = {}
    for idx, p in enumerate(ordered(problems)):
        for word in tokenize(p.title) + tokenize(" ".join(p.companies)):
            tokens.setdefault(word, set()).add(idx)

    prefixes: dict[str, set[str]] = {}
    for word in tokens:
        if len(word) < MIN_PREFIX:
            continue
        for size in range(MIN_PREFIX, len(word)):
            prefixes.setdefault(word[:size], set()).add(word)

    return {
        "schema_version": SCHEMA_VERSION,
        "count": len(problems),
        "min_prefix": MIN_PREFIX,
        "tokens": {w: sorted(rows) for w, rows in sorted(tokens.items())},
        "prefixes": {p: sorted(words) for p, words in sorted(prefixes.items())},
    }


def archive_document(existing: dict | None, additions: list[Problem]) -> dict:
    """Append-only record of every tombstone ever produced (D7).

    Deduplicated on ``(id, removed_on)``: a problem removed, restored, and
    removed again is genuinely two entries, but re-running today's sync twice is
    not.
    """
    entries = list((existing or {}).get("archived", []))
    seen = {(e.get("id"), e.get("removed_on")) for e in entries}
    for p in additions:
        if (p.id, p.removed_on) not in seen:
            entries.append(p.to_dict())
            seen.add((p.id, p.removed_on))
    entries.sort(key=lambda e: (e.get("removed_on") or "", e.get("key") or ""))
    return {
        "schema_version": SCHEMA_VERSION,
        "count": len(entries),
        "archived": entries,
    }


def changelog_section(result: DiffResult, problems: dict[str, Problem]) -> str:
    """One dated section, newest-first within the file."""
    lines = [f"## {result.date}", ""]
    for kind in KINDS:
        changes = result.of_kind(kind)
        if not changes:
            continue
        lines.append(f"### {_KIND_HEADINGS[kind]} ({len(changes)})")
        lines.append("")
        for change in changes[:CHANGELOG_MAX_PER_KIND]:
            lines.append(f"- {_describe(change, problems)}")
        if len(changes) > CHANGELOG_MAX_PER_KIND:
            rest = len(changes) - CHANGELOG_MAX_PER_KIND
            lines.append(f"- …and {rest} more (see `data/changes/{result.date}.json`)")
        lines.append("")
    if result.ambiguous_relinks:
        lines.append(f"### Needs confirmation ({len(result.ambiguous_relinks)})")
        lines.append("")
        for amb in result.ambiguous_relinks:
            lines.append(
                f"- {amb.title} — {len(amb.added_ids)} added / "
                f"{len(amb.removed_ids)} removed share one signature; not merged"
            )
        lines.append("")
    return "\n".join(lines)


def _describe(change, problems: dict[str, Problem]) -> str:
    if change.kind == RETITLED:
        return f"{change.before['title']} → {change.after['title']}"
    if change.kind == RELINKED:
        return f"{change.title} — {change.before['key']} → {change.after['key']}"
    if change.kind == RECOMPANIED:
        before = ", ".join(change.before["companies"]) or "none"
        after = ", ".join(change.after["companies"]) or "none"
        return f"{change.title} — {before} → {after}"
    if change.kind == REMOVED:
        return f"{change.title} — removed upstream"
    p = problems.get(change.id)
    if p is None:
        return change.title
    who = ", ".join(p.companies) or "Unattributed"
    return f"{change.title} — {who} · {p.format or 'unclassified'}"


def update_changelog(existing: str, section: str, date: str) -> str:
    """Insert or replace one dated section, keeping the file newest-first.

    Replacing rather than appending is what makes a same-day re-run idempotent:
    the second run of 2026-08-21 must not stack a duplicate section.
    """
    body = existing
    if body.startswith(CHANGELOG_TITLE):
        body = body[len(CHANGELOG_TITLE):].lstrip("\n")

    sections: list[tuple[str, str]] = []
    marks = list(_SECTION.finditer(body))
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        sections.append((mark.group(1), body[mark.start():end].rstrip("\n")))

    sections = [(d, text) for d, text in sections if d != date]
    sections.append((date, section.rstrip("\n")))
    sections.sort(key=lambda s: s[0], reverse=True)

    return CHANGELOG_TITLE + "\n\n" + "\n\n".join(text for _, text in sections) + "\n"


def write_text(path: Path, text: str) -> bool:
    """Write only when the content actually differs. Returns True if written."""
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def write_json(path: Path, doc: dict, *, compact: bool = True) -> bool:
    return write_text(path, dumps(doc, compact=compact))


def dumps(doc: dict, *, compact: bool = True) -> str:
    if compact:
        return json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def dumps_rows(doc: dict, key: str) -> str:
    """JSON with one record per line, so git diffs stay readable.

    ``json.dumps(indent=...)`` would explode every record across a dozen lines;
    a single compact line would make every diff look like the whole file
    changed. One record per line is the only shape that shows what moved.
    """
    rows = doc[key]
    out = ["{"]
    for k, v in doc.items():
        if k == key:
            continue
        out.append(f"{json.dumps(k, ensure_ascii=False)}:{json.dumps(v, ensure_ascii=False)},")
    out.append(f"{json.dumps(key, ensure_ascii=False)}:[")
    for i, row in enumerate(rows):
        out.append(json.dumps(row, ensure_ascii=False) + ("," if i < len(rows) - 1 else ""))
    out.append("]}")
    return "\n".join(out) + "\n"


def emit(
    root: Path,
    problems: dict[str, Problem],
    result: DiffResult | None,
    meta: Meta,
    changelog_path: Path | None = None,
) -> EmitReport:
    """Write the full artifact set under ``root``.

    ``dataset_changed`` on the report is what the sync job gates its commit on:
    it ignores ``meta.json``, whose timestamp changes on every run and would
    otherwise make an idempotent no-op sync look like a change (§6).
    """
    root = Path(root)
    report = EmitReport()

    def record(path: Path, changed: bool, counts_as_dataset: bool = True) -> None:
        try:
            name = str(path.relative_to(root))
        except ValueError:
            name = path.name
        (report.written if changed else report.unchanged).append(name)
        if changed and counts_as_dataset:
            report.dataset_changed = True

    problems_path = root / "problems.json"
    doc = problems_document(problems)
    if _only_volatile_changes(problems_path, doc):
        record(problems_path, False)
    else:
        record(problems_path, write_text(problems_path, dumps_rows(doc, "problems")))
    record(root / "index.json", write_json(root / "index.json", search_index(problems)))

    existing_archive = _read_archive(root / "archive.json")
    additions = list(result.archived) if result else []
    archive = archive_document(existing_archive, additions)
    record(
        root / "archive.json",
        write_text(root / "archive.json", dumps_rows(archive, "archived")),
    )

    # A day with no changes writes no change document at all. An empty one would
    # be committed noise, and it would overwrite latest.json -- which the
    # What's-new view reads -- with "nothing happened" on every quiet day.
    if result is not None and (result.changes or result.ambiguous_relinks):
        changes_dir = root / "changes"
        doc = result.to_dict()
        record(changes_dir / f"{result.date}.json", write_json(changes_dir / f"{result.date}.json", doc, compact=False))
        record(changes_dir / "latest.json", write_json(changes_dir / "latest.json", doc, compact=False))

        path = changelog_path or (root.parent / "CHANGELOG.md")
        existing = path.read_text(encoding="utf-8") if path.exists() else CHANGELOG_TITLE + "\n"
        record(
            path,
            write_text(
                path,
                update_changelog(existing, changelog_section(result, problems), result.date),
            ),
        )

    record(
        root / "meta.json",
        write_json(root / "meta.json", meta.to_dict(problems, result), compact=False),
        counts_as_dataset=False,
    )
    return report


def load_problems(path: Path) -> dict[str, Problem]:
    """Read a previously emitted problems.json back into memory.

    A missing file is the first-ever run and yields an empty dataset. An
    unreadable one is not: it would make every existing row look newly added and
    every tombstone vanish, so it fails instead.
    """
    path = Path(path)
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmitError(
            f"{path} exists but is not valid JSON ({exc}). Refusing to treat the "
            "committed dataset as empty; restore it from git history first."
        ) from None
    if not isinstance(doc, dict) or not isinstance(doc.get("problems"), list):
        raise EmitError(f"{path} is not a problems document. Refusing to proceed.")
    problems = [Problem.from_dict(row) for row in doc["problems"]]
    return {p.id: p for p in problems}


def _only_volatile_changes(path: Path, doc: dict) -> bool:
    """True when the committed file differs from ``doc`` in volatile fields only."""
    existing = _read_json_or_none(path)
    if not existing or not isinstance(existing.get("problems"), list):
        return False

    def strip(rows):
        return [
            {k: v for k, v in row.items() if k not in VOLATILE_FIELDS} for row in rows
        ]

    head_old = {k: v for k, v in existing.items() if k != "problems"}
    head_new = {k: v for k, v in doc.items() if k != "problems"}
    return head_old == head_new and strip(existing["problems"]) == strip(doc["problems"])


def _read_json_or_none(path: Path) -> dict | None:
    """Best-effort read, for callers where a missing or broken file just means
    'no prior information' -- never for the archive or the dataset."""
    if not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_archive(path: Path) -> dict | None:
    """Load the permanent archive, refusing to proceed if it is unreadable.

    Treating a corrupt archive as "no archive" would rewrite the permanent
    record of every tombstone with just today's handful -- destroying exactly
    the history D7 promises is never lost. A truncated file is an operator
    problem, not something to paper over.
    """
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EmitError(
            f"{path} exists but is not valid JSON ({exc}). Refusing to overwrite "
            "the permanent tombstone archive; restore it from git history first."
        ) from None
    if not isinstance(doc, dict) or not isinstance(doc.get("archived"), list):
        raise EmitError(
            f"{path} is not an archive document (expected an object with an "
            "'archived' list). Refusing to overwrite it."
        )
    return doc
