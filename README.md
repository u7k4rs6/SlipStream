# Slipstream

A personal, always-current tracker built on top of the public
[Tech-OA-Interview-Questions](https://github.com/perixtar/Tech-OA-Interview-Questions)
question bank: automatic daily sync, a personal study layer that survives every upstream
change, a daily diff of what moved, and a static browsing UI.

> **Status: working.** The sync pipeline runs end to end against live upstream, and the
> static frontend is browsable. Personal notes currently live in browser storage rather
> than the private repo of D2 — see [Personal data](#personal-data) below.

## Running it

```sh
pip install -e ".[dev]"      # no runtime dependencies; pytest for the suite
pytest -q                    # 177 tests

python -m slipstream.sync --data site/data     # fetch, parse, check, diff, emit
cd site && python3 -m http.server 8000         # then open http://localhost:8000
```

The site must be served over HTTP, not opened as a `file://` path: it loads its dataset
with `fetch`, which the file scheme blocks.

Useful sync flags: `--force` re-runs even when the upstream commit is unchanged, `--sha`
pins to a specific upstream commit, and `--offline DIR` reads local files instead of the
network.

## Hosting

`.github/workflows/sync.yml` runs the sync daily at 06:00 UTC, commits only when the
dataset actually moved, and opens an issue if a guardrail aborts the run.
`.github/workflows/pages.yml` publishes `site/` to GitHub Pages on every push that
touches it. Enable Pages with **Settings → Pages → Source: GitHub Actions**; no build
step is involved, because Preact and HTM are vendored rather than installed (D15).

## Personal data

Notes, status, difficulty, tags, and solution links are keyed by the derived problem ID,
so they survive upstream retitles, and they follow a problem across a relink through its
`aliases`. They are stored in `localStorage` for now — nothing to set up, but scoped to
one browser. **Progress → Export notes** writes a JSON file you can import elsewhere.
D2's design (a private repo written through a fine-grained PAT) is the intended
cross-device story and is not built yet; the storage layer is isolated in
`site/app/store.js` so it can be swapped without touching the UI.

The sync job has no write path to personal data in either arrangement.

## Documents

| Doc | What it covers |
| --- | --- |
| [docs/PRD.md](docs/PRD.md) | Problem, goals, requirements, risks, and the full decision log (D1–D20) |
| [docs/technical-architecture.md](docs/technical-architecture.md) | Step 0 findings on upstream, parsing strategy, stable ID derivation, diffing, persistence evaluation |
| [docs/security-and-access.md](docs/security-and-access.md) | Trust boundaries, PAT scoping and leak blast-radius, licensing posture, CI supply chain |
| [docs/frontend-spec.md](docs/frontend-spec.md) | Layout, filters, search performance budgets, personal-layer interactions |

## Code

| Path | What it does |
| --- | --- |
| `src/slipstream/parse.py` · `mdtable.py` · `schemas.py` | Upstream markdown → normalized rows, across all ten historical table schemas |
| `src/slipstream/companies.py` | Company vocabulary; splits `Zomato / Eternal / Amazon` into two companies, not three |
| `src/slipstream/model.py` | Stable IDs derived from the URL slug |
| `src/slipstream/diff.py` | added · removed · retitled · relinked · recompanied, plus tombstones and aliases |
| `src/slipstream/guards.py` | Abort thresholds — zero rows, >10% row loss, source divergence, unclassified rows |
| `src/slipstream/emit.py` | `problems.json`, search index, archive, change docs, meta, CHANGELOG |
| `src/slipstream/origins.py` | Maps problems to a login-free place to solve them (`origins.json`) |
| `src/slipstream/fetch.py` · `sync.py` | Pinned upstream fetch and the orchestrator |
| `site/` | The static frontend: browse, search, notes, what's-new, progress |

## Key findings from the upstream survey

Measured against `perixtar/Tech-OA-Interview-Questions` @ `d163035c` (2026-08-18), 1,944 rows:

- **The table schema has changed 10 times**, four of them in the last six weeks — so the
  parser is multi-schema and pinned to real fixtures, and an unknown header fails CI loudly
  rather than silently yielding zero rows.
- **Upstream is close to breaking its own README.** Its scripts hard-fail above 500,000 bytes;
  the file is at 443,709 with roughly 251 rows of headroom, and last month added 505. The
  sync therefore treats `formats/*.md` as primary and `README.md` as a cross-check.
- **There is no published per-problem ID**, but the URL slug is a strong derived key —
  1,236 of 1,293 slugs survived the largest observed monthly churn, and titles change
  *under* stable slugs.
- **There is no role field** (intern / new grad / full time) and never has been, so role type
  is a personal annotation here, never presented as upstream data.
- **Upstream carries no licence**, which is why this project mirrors metadata only.

## Attribution

Question data is sourced from
[perixtar/Tech-OA-Interview-Questions](https://github.com/perixtar/Tech-OA-Interview-Questions),
maintained by [FastPrep](https://www.fastprep.io). Slipstream is an unaffiliated personal
tracker. All problem content belongs to its original authors; this project stores only
factual metadata (company, title, link, format, dates) and links back to the source for every
problem. It never reproduces problem statements.

Project code will be released under a permissive licence; the upstream data is not ours to
license.
