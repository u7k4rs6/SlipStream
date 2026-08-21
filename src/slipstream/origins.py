"""Resolve each problem to somewhere it can actually be opened.

Upstream links every row to fastprep.io, which puts a sign-in wall in front of
the question itself -- so the "Practice" link cannot be followed without an
account. This module builds a second, login-free route to the same question.

It lives in its own artifact rather than as a field on ``Problem`` for two
reasons. The resolution depends on a *third* party (LeetCode's catalogue), so it
moves on a schedule of its own and must never be able to fail, stall, or dirty
the daily upstream sync. And a new field on every record would rewrite all ~1,900
rows of problems.json the day it lands, burying that day's real diff -- the one
thing emit.py exists to keep readable.

Coverage is small and that is the honest answer, not a bug: ~5% of the bank
resolves to a direct link, because the rest is fastprep's own OA write-ups, which
exist nowhere else under any title. Unmatched problems get no entry at all and
the frontend falls back to a web search it derives from the title -- baking ~1,800
search URLs would be a large artifact carrying nothing the client does not
already know.

Matching is precise rather than generous. A wrong link sends you off to
confidently solve the wrong question and to file notes against it; a missing one
just leaves the search fallback in place. So every ambiguity resolves to "no
match".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import emit
from .model import Problem

SCHEMA_VERSION = emit.SCHEMA_VERSION

# LeetCode's public problem list. Unauthenticated, unpaginated, ~2 MB, and the
# only endpoint of theirs that is stable enough to build on -- the GraphQL API
# behind the site changes shape without notice.
CATALOG_URL = "https://leetcode.com/api/problems/all/"
PROBLEM_URL = "https://leetcode.com/problems/{slug}/"
USER_AGENT = "slipstream-origins (+https://github.com/)"
TIMEOUT = 30

_DIFFICULTY = {1: "Easy", 2: "Medium", 3: "Hard"}

_WORD = re.compile(r"[a-z0-9]+")

# Dropped before comparing token sets, so "Search in a Rotated Sorted Array"
# still meets "Search in Rotated Sorted Array". Deliberately tiny: every word
# added here is a word two different questions are allowed to differ by.
#
# "and" is NOT in here, and must not be: LeetCode has "Maximum AND Sum of Array",
# where the AND is the bitwise operator. Dropping it matched that question to a
# fastprep row about a plain maximum sum.
_STOPWORDS = frozenset("a an the of in to with for".split())

# Upstream abbreviates where LeetCode spells out. These are pure spelling
# variants -- expanding them cannot change which question a title names -- so
# both sides are expanded before comparison. Anything whose expansion could
# alter the meaning does not belong here.
_ABBREVIATIONS = {
    "min": "minimum", "max": "maximum", "num": "number", "len": "length",
    "str": "string", "arr": "array", "char": "character", "dup": "duplicate",
    "avg": "average", "freq": "frequency",
}

# Stripped from the *front of upstream's title only*, never from LeetCode's.
# "Is Happy Number" and "Implement an LRU Cache" are upstream dressing on a
# canonical name; stripping the catalogue side too would make "Find Maximum
# Score" and "Get the Maximum Score" collide, which is a guess, not a match.
_LEADING_VERBS = frozenset(
    "get find implement is compute calculate return determine".split()
)

# Only these formats can have a LeetCode original at all. Without the gate,
# "Design a Web Crawler" (system design) resolves to LeetCode 1236 "Web Crawler"
# -- a totally different exercise that happens to share a name.
ELIGIBLE_FORMATS = frozenset({"Coding", "SQL"})


class OriginError(Exception):
    """The catalogue could not be read. Never a reason to emit an empty map --
    that would silently strip every direct link the site already publishes."""


@dataclass(frozen=True)
class Entry:
    """One LeetCode question, as much of it as we need to link to it."""

    slug: str
    title: str
    paid: bool
    difficulty: str | None

    @property
    def url(self) -> str:
        return PROBLEM_URL.format(slug=self.slug)

    def to_dict(self) -> dict:
        doc = {"site": "leetcode", "url": self.url, "title": self.title}
        if self.difficulty:
            doc["difficulty"] = self.difficulty
        # Premium questions are their own sign-in wall, so the UI has to be able
        # to say so rather than promise a link that opens onto another paywall.
        if self.paid:
            doc["paid"] = True
        return doc


@dataclass
class Catalog:
    """Every LeetCode question, indexed by each shape ``match`` looks it up by.

    Titles that are not unique under an index are *removed* from it rather than
    kept with one arbitrary winner: an ambiguous match is exactly the case where
    guessing does the damage this module is written to avoid.
    """

    by_title: dict[str, Entry]
    by_signature: dict[frozenset[str], Entry]
    by_reduced: dict[frozenset[str], Entry]
    size: int


def normalize(title: str) -> str:
    return " ".join(_WORD.findall(title.lower()))


def signature(title: str) -> frozenset[str]:
    """Order- and stopword-insensitive fingerprint of a title."""
    return frozenset(t for t in normalize(title).split() if t not in _STOPWORDS)


def _stem(token: str) -> str:
    """Crudest possible plural fold, so "Merge Interval" meets "Merge Intervals".

    Short tokens are left alone: "abs", "gas", "bus" are not plurals, and a
    stemmer that mangles them would fabricate collisions rather than find them.
    """
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def reduced(title: str, *, strip_verb: bool = False) -> frozenset[str]:
    """Fingerprint with upstream's spelling habits normalised away."""
    tokens = normalize(title).split()
    if strip_verb and tokens and tokens[0] in _LEADING_VERBS:
        tokens = tokens[1:]
    return frozenset(
        _stem(_ABBREVIATIONS.get(t, t)) for t in tokens if t not in _STOPWORDS
    )


def parse_catalog(payload: str | bytes) -> Catalog:
    try:
        doc = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise OriginError(f"catalogue is not valid JSON ({exc})") from None
    pairs = doc.get("stat_status_pairs") if isinstance(doc, dict) else None
    if not isinstance(pairs, list) or not pairs:
        raise OriginError(
            "catalogue has no 'stat_status_pairs' list; the endpoint changed shape"
        )

    titles: dict[str, list[Entry]] = {}
    signatures: dict[frozenset[str], list[Entry]] = {}
    reductions: dict[frozenset[str], list[Entry]] = {}
    for pair in pairs:
        stat = (pair or {}).get("stat") or {}
        slug = stat.get("question__title_slug")
        title = stat.get("question__title")
        if not slug or not title:
            continue
        entry = Entry(
            slug=slug,
            title=title,
            paid=bool(pair.get("paid_only")),
            difficulty=_DIFFICULTY.get(((pair.get("difficulty") or {}).get("level"))),
        )
        # An empty key would match every other empty key -- a title of nothing
        # but stopwords or punctuation must index under nothing at all.
        for table, key in (
            (titles, normalize(title)),
            (signatures, signature(title)),
            (reductions, reduced(title)),
        ):
            if key:
                table.setdefault(key, []).append(entry)

    return Catalog(
        by_title=_unique(titles),
        by_signature=_unique(signatures),
        # Built without verb-stripping on purpose (see _LEADING_VERBS). Folding
        # abbreviations and plurals makes a handful of distinct LeetCode titles
        # collide; _unique drops every one of those rather than pick a winner.
        by_reduced=_unique(reductions),
        size=sum(len(v) for v in titles.values()),
    )


def _unique(grouped: dict) -> dict:
    return {k: v[0] for k, v in grouped.items() if len(v) == 1}


def fetch_catalog(url: str = CATALOG_URL) -> Catalog:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise OriginError(f"GET {url} -> {exc.code} {exc.reason}") from None
    except urllib.error.URLError as exc:
        raise OriginError(f"GET {url} failed: {exc.reason}") from None
    if not payload:
        raise OriginError(f"{url} returned an empty body")
    return parse_catalog(payload)


def match(title: str, catalog: Catalog) -> Entry | None:
    """The one LeetCode question this title certainly names, or None.

    Four lookups, widening in order, every one of them requiring a *unique* hit:

    1. Exact normalized title -- the only match that needs no judgement at all.
    2. Token-set fingerprint, for titles differing by an article or word order
       ("Reverse An Integer" / "Reverse Integer").
    3. The same, with upstream's abbreviations and plurals folded in
       ("Num of Good Pairs" / "Number of Good Pairs").
    4. As 3, minus a leading imperative verb ("Is Happy Number" / "Happy
       Number").

    And nothing looser. Matching on the URL slug was tried and thrown away: it
    resolves ~47 more rows and roughly a quarter of them are wrong, including
    "Shopping and Billing" -> "Palindromic Substrings" and "Design an
    Authenticated Page Presence Counter" -> "Counter". Title-overlap scoring
    does not separate those from the good ones, because upstream's questions are
    frequently deliberate *variants* of a LeetCode problem -- "Longest
    Palindromic Subarray" is not "Longest Palindromic Substring", and no
    similarity threshold can know that. One extra token is routinely the entire
    difference between two neighbouring questions, so the widening stops here.
    """
    if not title:
        return None
    lookups = (
        (catalog.by_title, normalize(title)),
        (catalog.by_signature, signature(title)),
        (catalog.by_reduced, reduced(title)),
        (catalog.by_reduced, reduced(title, strip_verb=True)),
    )
    for table, key in lookups:
        if not key:          # see parse_catalog: empty keys index nothing
            continue
        hit = table.get(key)
        if hit is not None:
            return hit
    return None


def eligible(problem: Problem) -> bool:
    """Whether this problem could have a LeetCode original at all (ELIGIBLE_FORMATS)."""
    return problem.format in ELIGIBLE_FORMATS


def resolve(problems: dict[str, Problem], catalog: Catalog) -> dict[str, dict]:
    """Map problem ID -> origin record, omitting everything unmatched.

    ``match`` answers "does this string name a LeetCode question"; the format
    gate lives here because it is a fact about the *problem*, not the title.
    """
    origins: dict[str, dict] = {}
    for problem in problems.values():
        if not eligible(problem):
            continue
        found = match(problem.title, catalog)
        if found is not None:
            origins[problem.id] = found.to_dict()
    return origins


def origins_document(origins: dict[str, dict], catalog_size: int) -> dict:
    """Sorted by ID and carrying no timestamp, so a re-run against an unchanged
    catalogue produces a byte-identical file and commits nothing."""
    return {
        "schema_version": SCHEMA_VERSION,
        "source": CATALOG_URL,
        "catalog_count": catalog_size,
        "count": len(origins),
        "origins": {k: origins[k] for k in sorted(origins)},
    }


def build(data_root: Path, catalog: Catalog) -> tuple[dict, bool]:
    """Resolve the committed dataset and write ``origins.json``.

    Returns the document and whether the file actually changed.
    """
    data_root = Path(data_root)
    problems = emit.load_problems(data_root / "problems.json")
    if not problems:
        raise OriginError(
            f"{data_root / 'problems.json'} holds no problems; run the sync first"
        )
    doc = origins_document(resolve(problems, catalog), catalog.size)
    changed = emit.write_text(data_root / "origins.json", emit.dumps(doc, compact=False))
    return doc, changed


def _report_to_ci(changed: bool, count: int) -> None:
    """Publish the outcome as a GitHub Actions step output.

    Same reason sync.py has one: the sync's own no-op discard reverts the whole
    of site/data, so the workflow has to be told which file to hold back rather
    than inferring it from a working tree that always looks dirty.
    """
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"origins_changed={'true' if changed else 'false'}\n")
        handle.write(f"origins_count={count}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="slipstream-origins",
        description="Map problems to a login-free place to solve them.",
    )
    parser.add_argument("--data", default="site/data", type=Path,
                        help="directory holding problems.json (default: site/data)")
    parser.add_argument("--catalog", default=None, type=Path,
                        help="read the LeetCode catalogue from a file instead of the network")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would resolve without writing anything")
    args = parser.parse_args(argv)

    try:
        catalog = (
            parse_catalog(args.catalog.read_bytes())
            if args.catalog
            else fetch_catalog()
        )
        if args.dry_run:
            problems = emit.load_problems(args.data / "problems.json")
            if not problems:
                raise OriginError(
                    f"{args.data / 'problems.json'} holds no problems; run the sync first"
                )
            origins = resolve(problems, catalog)
            doc = origins_document(origins, catalog.size)
            changed = None
        else:
            doc, changed = build(args.data, catalog)
    except (OriginError, emit.EmitError) as exc:
        print(f"ORIGINS FAILED: {exc}", file=sys.stderr)
        return 1

    total = doc["count"]
    paid = sum(1 for v in doc["origins"].values() if v.get("paid"))
    print(f"catalogue: {doc['catalog_count']} LeetCode questions")
    print(f"  resolved: {total} direct links ({paid} LeetCode Premium)")
    if changed is not None:
        print(f"  origins.json {'written' if changed else 'unchanged'}")
        _report_to_ci(changed, total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
