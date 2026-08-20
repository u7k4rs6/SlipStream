"""Fetch upstream sources, pinned to one commit.

Every run resolves the branch head to a SHA first and then fetches *only* by
that SHA. Upstream commits hourly, so fetching by branch name risks reading
README.md from one commit and formats/coding.md from the next -- which would
show up downstream as a phantom divergence between the two sources, or worse,
as rows that appear to have been added and removed in the same sync.

The SHA is also the cache key: if it matches what meta.json already records,
the whole run is a no-op and nothing needs downloading at all.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

UPSTREAM_REPO = "perixtar/Tech-OA-Interview-Questions"
UPSTREAM_BRANCH = "master"
USER_AGENT = "slipstream-sync (+https://github.com/)"
TIMEOUT = 30


@dataclass(frozen=True)
class Source:
    """One upstream document and the format its rows are known to carry.

    The formats pages have no Format column -- the page *is* the format -- and
    the route cannot recover it, since SQL and Coding both live under
    /problems/. So the hint is not a convenience here; without it every SQL
    question on formats/sql.md is labelled Coding.
    """

    path: str
    format_hint: str | None = None
    primary: bool = False


# README is the cross-check, not the primary source (arch §3.1): upstream's own
# scripts hard-fail above 500,000 bytes and README is at ~443,709, so it is the
# file most likely to be split or truncated first.
SOURCES = (
    Source("README.md", None, primary=False),
    Source("formats/coding.md", "Coding", primary=True),
    Source("formats/sql.md", "SQL", primary=True),
    Source("formats/system-design.md", "System design", primary=True),
    Source("formats/low-level-design.md", "Low-level design", primary=True),
    Source("formats/ai-coding.md", "AI coding", primary=True),
)

COMPANY_DOMAINS = "assets/company-domains.json"


class FetchError(Exception):
    """Upstream could not be read. Never a reason to emit an empty dataset."""


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code == 403:
            hint = " (GitHub rate limit? set GITHUB_TOKEN in CI)"
        elif exc.code == 404:
            hint = " (upstream moved or renamed this path)"
        raise FetchError(f"GET {url} -> {exc.code} {exc.reason}{hint}") from None
    except urllib.error.URLError as exc:
        raise FetchError(f"GET {url} failed: {exc.reason}") from None


def head_sha(repo: str = UPSTREAM_REPO, branch: str = UPSTREAM_BRANCH) -> str:
    url = f"https://api.github.com/repos/{repo}/commits/{branch}"
    try:
        sha = json.loads(_get(url))["sha"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise FetchError(f"{url} did not return a commit SHA") from None
    if not isinstance(sha, str) or len(sha) < 7:
        raise FetchError(f"{url} returned an implausible SHA: {sha!r}")
    return sha


def fetch_file(path: str, sha: str, repo: str = UPSTREAM_REPO) -> str:
    raw = _get(f"https://raw.githubusercontent.com/{repo}/{sha}/{path}")
    if not raw:
        raise FetchError(f"{path}@{sha[:8]} is empty; refusing to treat that as data")
    return raw.decode("utf-8")


def fetch_all(sha: str, repo: str = UPSTREAM_REPO) -> dict[str, str]:
    """Every source plus the company vocabulary, all at the same commit."""
    wanted = [s.path for s in SOURCES] + [COMPANY_DOMAINS]
    return {path: fetch_file(path, sha, repo) for path in wanted}
