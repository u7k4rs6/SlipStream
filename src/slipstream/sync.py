"""The daily sync: fetch, parse, check, diff, emit.

This is the only module that composes the others, and the only one that decides
whether a run is trustworthy enough to commit. Everything it calls is a pure
function over data it was handed, so a failure here can never corrupt what is
already committed -- and it has no write path at all to the personal layer (D2).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from . import companies, diff, emit, fetch, guards, parse
from .model import Problem
from .schemas import UnknownSchemaError


@dataclass
class SyncOutcome:
    sha: str
    changed: bool = False
    problems: dict[str, Problem] = field(default_factory=dict)
    result: diff.DiffResult | None = None
    report: emit.EmitReport | None = None
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False          # upstream SHA unchanged; nothing to do


def read_sources(sha: str, offline: Path | None = None) -> dict[str, str]:
    """Upstream documents, either fetched or read from a local snapshot."""
    if offline is None:
        return fetch.fetch_all(sha)
    texts = {}
    for path in [s.path for s in fetch.SOURCES] + [fetch.COMPANY_DOMAINS]:
        local = offline / Path(path).name
        if not local.exists():
            raise fetch.FetchError(f"offline snapshot is missing {local}")
        texts[path] = local.read_text(encoding="utf-8")
    return texts


def build_dataset(
    texts: dict[str, str], today: date
) -> tuple[dict[str, Problem], list[str], dict[str, set[str]]]:
    """Parse every source into one normalized dataset.

    Returns ``(problems, warnings, ids_by_group)`` where the groups are the
    README's row IDs and the formats pages' row IDs, kept apart so they can be
    cross-checked against each other before anything is committed.
    """
    vocab = companies.from_sources(
        domains_json=texts.get(fetch.COMPANY_DOMAINS),
        readme_text=texts.get("README.md"),
    )

    rows = []
    warnings: list[str] = []
    ids: dict[str, set[str]] = {"readme": set(), "formats": set()}

    for source in fetch.SOURCES:
        text = texts.get(source.path)
        if text is None:
            raise fetch.FetchError(f"missing source {source.path}")
        parsed, report = parse.parse_document(text, source.path, source.format_hint)
        warnings += [f"{source.path}: {w}" for w in report.warnings]
        warnings += [f"{source.path}: skipped {s}" for s in report.skipped]

        group = "formats" if source.primary else "readme"
        for row in parsed:
            ids[group].add(_row_id(row, vocab))
        rows += parsed

    merged_report = parse.ParseReport(source="merged")
    problems = parse.normalize(rows, vocab, today, merged_report)
    warnings += [f"merged: {w}" for w in merged_report.warnings]
    return problems, warnings, ids


def _row_id(row, vocab) -> str:
    from . import model

    key = model.derive_key(row.url) if row.url else None
    if not key:
        names, _ = vocab.split_cell(row.company_cell)
        key = model.fallback_key(row.title or "", names)
    return model.derive_id(key)


def sync(
    data_root: Path,
    today: date | None = None,
    sha: str | None = None,
    offline: Path | None = None,
    force: bool = False,
    changelog_path: Path | None = None,
) -> SyncOutcome:
    """Run one sync. Raises SyncAbort or UnknownSchemaError rather than
    committing anything it cannot vouch for."""
    today = today or datetime.now(timezone.utc).date()
    data_root = Path(data_root)
    sha = sha or (fetch.head_sha() if offline is None else "offline")

    previous_meta = emit._read_json_or_none(data_root / "meta.json")
    if not force and previous_meta and previous_meta.get("upstream_sha") == sha:
        # Same commit as last time: upstream cannot have changed, so there is
        # nothing to download, diff, or commit.
        return SyncOutcome(sha=sha, skipped=True)

    texts = read_sources(sha, offline)
    problems, warnings, ids = build_dataset(texts, today)

    previous = emit.load_problems(data_root / "problems.json")
    previous_live = sum(1 for p in previous.values() if p.state != "removed")

    guards.check_row_count(previous_live, len(problems))
    warnings += guards.check_divergence(ids["readme"], ids["formats"])
    guards.check_unclassified(problems)

    result = diff.diff(previous, problems, today)
    meta = emit.Meta(
        upstream_sha=sha,
        synced_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        sources={path: emit.source_digest(text) for path, text in sorted(texts.items())},
        warnings=warnings,
    )
    report = emit.emit(data_root, result.problems, result, meta, changelog_path)

    return SyncOutcome(
        sha=sha,
        changed=report.dataset_changed,
        problems=result.problems,
        result=result,
        report=report,
        warnings=warnings,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="slipstream-sync", description="Sync the upstream question bank."
    )
    parser.add_argument("--data", default="site/data", type=Path,
                        help="directory to emit artifacts into (default: site/data)")
    parser.add_argument("--changelog", default=None, type=Path,
                        help="path to CHANGELOG.md (default: <data>/../../CHANGELOG.md)")
    parser.add_argument("--sha", default=None,
                        help="pin to a specific upstream commit instead of the branch head")
    parser.add_argument("--offline", default=None, type=Path,
                        help="read sources from a local directory instead of the network")
    parser.add_argument("--force", action="store_true",
                        help="re-run even if the upstream SHA is unchanged")
    args = parser.parse_args(argv)

    changelog = args.changelog or Path("CHANGELOG.md")
    try:
        outcome = sync(args.data, sha=args.sha, offline=args.offline,
                       force=args.force, changelog_path=changelog)
    except (guards.SyncAbort, UnknownSchemaError, fetch.FetchError, emit.EmitError) as exc:
        print(f"SYNC ABORTED: {exc}", file=sys.stderr)
        return 1

    if outcome.skipped:
        print(f"upstream unchanged at {outcome.sha[:8]}; nothing to do")
        return 0

    counts = outcome.result.counts if outcome.result else {}
    live = sum(1 for p in outcome.problems.values() if p.state != "removed")
    print(f"upstream {outcome.sha[:8]}: {live} live rows, {len(outcome.problems)} total")
    print("  changes: " + (", ".join(f"{k}={v}" for k, v in counts.items() if v) or "none"))
    if outcome.result and outcome.result.ambiguous_relinks:
        print(f"  NEEDS CONFIRMATION: {len(outcome.result.ambiguous_relinks)} ambiguous relinks")
    for warning in outcome.warnings[:20]:
        print(f"  warning: {warning}")
    if len(outcome.warnings) > 20:
        print(f"  ... and {len(outcome.warnings) - 20} more warnings")
    print(f"  {outcome.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
