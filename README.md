# Slipstream

A personal, always-current tracker built on top of the public
[Tech-OA-Interview-Questions](https://github.com/perixtar/Tech-OA-Interview-Questions)
question bank: automatic daily sync, a personal study layer that survives every upstream
change, a daily diff of what moved, and a static browsing UI.

> **Status: early implementation.** Parsing, normalization, diffing, the abort
> guardrails, and the artifact emitter are built and tested against pinned upstream
> fixtures (`pytest -q`). The scheduled sync job, personal-layer persistence, and the
> frontend are not written yet.

## Documents

| Doc | What it covers |
| --- | --- |
| [docs/PRD.md](docs/PRD.md) | Problem, goals, requirements, risks, and the full decision log (D1–D20) |
| [docs/technical-architecture.md](docs/technical-architecture.md) | Step 0 findings on upstream, parsing strategy, stable ID derivation, diffing, persistence evaluation |
| [docs/security-and-access.md](docs/security-and-access.md) | Trust boundaries, PAT scoping and leak blast-radius, licensing posture, CI supply chain |
| [docs/frontend-spec.md](docs/frontend-spec.md) | Layout, filters, search performance budgets, personal-layer interactions |

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
