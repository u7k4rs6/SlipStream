"""Company vocabulary, splitting, and canonicalisation.

The hard problem here is that upstream joins multiple companies with " / ", but
at least one company *name* contains a slash: "Zomato / Eternal" is one company
(Zomato renamed itself Eternal), while "Zomato / Eternal / Amazon" is two.
Naive splitting invents a phantom company called "Eternal".

Upstream gives us the data to resolve this: assets/company-domains.json keys
"Zomato / Eternal" as a single entry, and the curated company list in the README
lists it as one item. We use both as a vocabulary and match longest-first.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .schemas import SENTINEL_COMPANIES

SEPARATOR = re.compile(r"\s+/\s+")

# Curated list lives in a <details> block; the line is a comma-separated run of
# names terminated by a full stop.
_LIST_MARKER = re.compile(r"Full company list", re.I)


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


@dataclass
class CompanyVocabulary:
    """Known company names, used to disambiguate slash-joined cells."""

    canonical: dict[str, str] = field(default_factory=dict)  # normalised -> display
    _max_parts: int = 1

    def add(self, name: str, *, authoritative: bool = False) -> None:
        name = " ".join(name.split())
        if not name:
            return
        key = _norm(name)
        existing = self.canonical.get(key)
        if existing is None or authoritative or _prefer(name, existing):
            self.canonical[key] = name
        self._max_parts = max(self._max_parts, len(SEPARATOR.split(name)))

    def __contains__(self, name: str) -> bool:
        return _norm(name) in self.canonical

    def display(self, name: str) -> str:
        return self.canonical.get(_norm(name), " ".join(name.split()))

    def __len__(self) -> int:
        return len(self.canonical)

    def split_cell(self, cell: str) -> tuple[list[str], list[str]]:
        """Split a company cell into canonical company names.

        Returns ``(companies, unknown)``. ``unknown`` lists tokens not present in
        the vocabulary; they are still returned as companies (a genuinely new
        company must not be dropped) but are reported so the sync can warn.
        """
        text = " ".join(cell.split())
        if not text:
            return [], []
        if _norm(text) in SENTINEL_COMPANIES:
            return [], []

        parts = SEPARATOR.split(text)
        out: list[str] = []
        unknown: list[str] = []
        i = 0
        while i < len(parts):
            # Longest match first: try the longest run of consecutive tokens that
            # the vocabulary knows, so "Zomato / Eternal" wins over "Zomato".
            upper = min(len(parts), i + self._max_parts)
            for j in range(upper, i, -1):
                candidate = " / ".join(parts[i:j])
                if candidate in self:
                    out.append(self.display(candidate))
                    i = j
                    break
            else:
                token = parts[i]
                if _norm(token) in SENTINEL_COMPANIES:
                    i += 1
                    continue
                out.append(self.display(token))
                if token not in self:
                    unknown.append(token)
                i += 1
        return out, unknown


def _prefer(new: str, old: str) -> bool:
    """Tie-break between spelling variants of the same name.

    Upstream lists both "Infosys" and "infosys", and both "MathWorks" and
    "Mathworks". Prefer the variant with more uppercase characters, which picks
    the conventional brand spelling, and break exact ties deterministically.
    """
    nu, ou = sum(c.isupper() for c in new), sum(c.isupper() for c in old)
    if nu != ou:
        return nu > ou
    return new < old


def from_sources(
    domains_json: str | None = None,
    readme_text: str | None = None,
    extra: list[str] | None = None,
) -> CompanyVocabulary:
    """Build a vocabulary from upstream's own data.

    ``assets/company-domains.json`` is authoritative: its keys are curated and
    include the slash-containing names we most need to protect.
    """
    vocab = CompanyVocabulary()
    if domains_json:
        try:
            for name in json.loads(domains_json):
                vocab.add(name, authoritative=True)
        except (json.JSONDecodeError, TypeError):
            pass
    if readme_text:
        for name in _names_from_readme(readme_text):
            vocab.add(name)
    for name in extra or []:
        vocab.add(name)
    return vocab


def _names_from_readme(text: str) -> list[str]:
    """Pull the curated company list out of the README's <details> block."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not _LIST_MARKER.search(line):
            continue
        for candidate in lines[i + 1 : i + 8]:
            candidate = candidate.strip()
            if candidate.count(",") >= 10:
                return [
                    part.strip()
                    for part in candidate.rstrip(".").split(",")
                    if part.strip()
                ]
    return []
