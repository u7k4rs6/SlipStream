# Slipstream — Security, Access, and Licensing

**Status:** Decisions ratified 2026-08-20 · Ready to build
**Date:** 2026-08-20 · Decision log in `PRD.md` §10.

---

## 1. Trust boundaries

| Plane | Trust | Secrets | Can write |
| --- | --- | --- | --- |
| Upstream repo | Untrusted input | none | nothing |
| Sync job (Actions) | Trusted code, untrusted data | `GITHUB_TOKEN` only | `slipstream` mirror + data |
| Public site (Pages) | Public, world-readable | none baked in | nothing server-side |
| Browser session | User-controlled | fine-grained PAT in `localStorage` | `slipstream-personal` only |
| Personal repo | Private | — | — |

Two properties are structural rather than procedural:

1. **The sync job has no credential for the personal repo.** Its `GITHUB_TOKEN` is scoped to
   `slipstream` and cannot reach `slipstream-personal`. A parser bug cannot destroy personal
   data because it has no path to it. This is why the personal layer is a *separate repo*
   rather than a separate file.
2. **Upstream content is untrusted input.** It is markdown authored by a third party and
   rendered into our UI.

## 2. Upstream access — read-only, no credentials

- Reads go to `raw.githubusercontent.com` (verified: HTTP 200 unauthenticated, strong `ETag`,
  `cache-control: max-age=300`) or a shallow `git clone`. Either is anonymous.
- **No credentials of any kind for upstream.** None are needed; none will be created.
- **No third-party scraping.** Upstream's own `sync-practice-formats.py` calls
  `https://www.fastprep.io/api/*`. **We do not.** We read only what upstream has already
  committed to its public repo. This keeps us inside the stated constraint and off anyone
  else's rate limits and ToS.
- Unauthenticated GitHub API is 60 req/hr per IP; raw fetches are separate and generous. One
  daily sync fetching six files is far inside both. Actions runners share IPs, so the sync
  uses the job's `GITHUB_TOKEN` for API calls (5,000 req/hr) and plain raw fetches for file
  content.
- Pin the **immutable repo id `687227685`**, not the name. The repo has already been renamed
  once (`perixtar/2026-Tech-OA-by-FastPrep` → `perixtar/Tech-OA-Interview-Questions`; the old
  name now returns `301 Moved Permanently`). A future rename must not silently break or, worse,
  silently start reading a *different* repo that took over the old name.

## 3. The PAT — scoping and blast radius

### 3.1 Exact scoping

| Setting | Value |
| --- | --- |
| Type | **Fine-grained** personal access token (never classic) |
| Resource owner | your account |
| Repository access | **Only select repositories → `slipstream-personal`** |
| Permissions | **Contents: Read and write.** Nothing else. |
| Explicitly NOT granted | Actions, Workflows, Administration, Secrets, Packages, Webhooks, Pages, Metadata-write, org access, user/email/gist scopes |
| Expiry | **90 days (D13)**, set explicitly |

A **classic** PAT is unacceptable here: `repo` scope on a classic token grants read/write to
**every** repository the account can touch, public and private. Fine-grained scoping is the
entire reason the risk is tolerable.

### 3.2 What a leaked token could actually do

Assume full compromise of the token — copied out of `localStorage` via XSS, taken from a
synced browser profile, or pasted somewhere careless.

**It can:**
- Read `slipstream-personal` — every note, status, difficulty rating, and solution link. If
  notes contain candid remarks about companies or interviews, **those are exposed.**
- Overwrite or delete `personal.json`, and commit arbitrary files to that repo.
- Rewrite that repo's history within the limits of the Contents API.
- Consume API quota for that repo.

**It cannot:**
- Touch **any** other repository — not the public `slipstream` repo, not the Pages site, not
  anything else you own. The site cannot be defaced with this token.
- Modify GitHub Actions workflows or secrets (no Actions/Workflows permission), so it cannot
  achieve code execution in CI or pivot.
- Delete the repository (that needs Administration).
- Read your email, profile, gists, org data, or packages.
- Do anything at all after expiry.

**Realistic worst case: a private study journal is read, and one JSON file is vandalised.**
The vandalism is fully recoverable — git history in that repo *is* the backup, and the
IndexedDB cache in each browser holds a recent copy. The disclosure is not recoverable, which
is the reason to keep notes non-sensitive (§3.4).

### 3.3 Handling

- The token is entered by the user into the running site and stored in `localStorage`. It is
  **never** committed, never placed in a `.env` in the repo, never a GitHub Actions secret
  (the sync job must not have it — see §1).
- Stored under one obvious key so it can be cleared; the UI provides an explicit **"Forget
  token"** button that clears it and the cache.
- Requests go only to `https://api.github.com`. A strict CSP (§5) prevents a token being
  posted anywhere else even if script injection occurs.
- **Rotation:** 90-day expiry forces periodic re-issue. Revoke immediately at
  Settings → Developer settings → Fine-grained tokens if a device is lost.
- Never logged, never put in a URL, never sent to any analytics.

### 3.4 Residual risk, stated plainly

Holding a write-capable token in browser `localStorage` on a public origin is the weakest
point in this design. It is accepted because the scope is one private repo of study notes and
the alternative (a hosted DB) trades it for a different always-present browser key plus a
vendor dependency that pauses on inactivity.

**Mitigating guidance:** treat `personal.json` as *potentially disclosable*. Keep notes about
solutions and technique; avoid recording anything under NDA, anything identifying an
interviewer, or verbatim proprietary interview content.

If this residual risk is unacceptable, the alternative is Option B in
`technical-architecture.md` §7 — say so and it will be re-scoped.

> **DECIDED (D11): accepted.** A browser-held, single-repo, 90-day fine-grained token is the
> chosen tradeoff. The controls that make it acceptable are binding: text-node-only rendering
> (§5), strict CSP restricting `connect-src` to `api.github.com`, an explicit "Forget token"
> control, and keeping notes non-sensitive per §3.4.
>
> **DECIDED (D14): notes are stored in plaintext**, not encrypted. Encryption would add a
> passphrase, break diffability, and make recovery harder, in exchange for protecting data we
> have already decided should not be sensitive. The mitigation is what goes *into* the notes,
> not a cipher around them.

## 4. Licensing and attribution

### 4.1 The finding

**The upstream repository has no licence.** Verified two ways: no `LICENSE`/`COPYING` file in
the tree, and the GitHub API returns `"license": null`.

Under default copyright, "no licence" means **all rights reserved**. Public visibility and
GitHub's ToS grant the right to *view* and to *fork within GitHub*, but **no general licence
to copy, redistribute, or republish the content elsewhere** — which is exactly what
republishing a mirror on GitHub Pages would be.

The content also has a further wrinkle: it is community-reported interview questions,
assembled by a commercial entity (FastPrep) and pointing exclusively at that company's site.

**I am not a lawyer and this is not legal advice.** It is a flag that the safe posture and the
maximal posture differ, and that the choice is yours.

### 4.2 Recommended posture — metadata only, link out

1. **Publish only factual metadata**: company name, problem title, the upstream URL, format,
   dates. Facts and short titles are the thinnest possible use, and this is all the tracker
   actually needs.
2. **Never mirror problem statements.** We do not fetch them at all (§2), so there is nothing
   to leak into the mirror.
3. **Link out to `www.fastprep.io`** for every problem. Traffic continues to flow to the
   source; we are an index, not a replacement.
4. **Attribute prominently** — site footer and repo README:
   > Question data sourced from
   > [perixtar/Tech-OA-Interview-Questions](https://github.com/perixtar/Tech-OA-Interview-Questions),
   > maintained by [FastPrep](https://www.fastprep.io). Slipstream is an unaffiliated personal
   > tracker. All problem content belongs to its original authors.
5. **Do not reproduce upstream branding** — logo, Discord invite, or badges.
6. **Reconsider committing `mirror/` verbatim.** Storing a full copy of a
   no-licence README is the most copy-like thing in the design. Recommendation: store the
   upstream **commit SHA** plus our normalized metadata, which is reproducible and far
   thinner. **DECIDED (D8): SHA + normalized data only** — see `technical-architecture.md` §10.
7. **Honour a takedown immediately** if the maintainer objects, and keep the repo easy to make
   private.
8. **Our own licence:** license *our code* (MIT/Apache-2.0) but explicitly state that the
   **data is not ours to license**.

### 4.3 Note on personal use

If `slipstream` is kept **private** and Pages is not used, essentially all of §4.2's concern
evaporates — private personal reference is the least contentious use. The tension exists only
because GitHub Pages on the free tier **requires a public repo**.

> **DECIDED (D5): metadata only.** Company, title, URL, format and dates. Never problem
> statements, and per **D8** not even a verbatim README mirror — only the upstream commit SHA
> plus our normalized data. Pinned test fixtures are the sole exception, and exist to make an
> upstream format change fail loudly.
>
> **DECIDED (D12): the site is public**, with the attribution in §4.2(4) rendered in the site
> footer and repo README. The combination of metadata-only, link-out, no upstream branding, and
> prompt takedown compliance is the posture we ship.
>
> **DECIDED (D4): yes, surface the Practice links.** Sending traffic to the source is part of
> the attribution posture, not a cost of it.

## 5. Public vs private, and site hardening

| Asset | Visibility | Rationale |
| --- | --- | --- |
| `slipstream` code + parser + tests | Public | No secrets; enables Pages |
| `data/problems.json`, changes, CHANGELOG | Public | Metadata only, per §4.2 |
| Pages site | Public | Free-tier requirement |
| `slipstream-personal` | **Private** | Notes, status, solution links |
| PAT | Browser `localStorage` only | Never in either repo |

**Upstream markdown is untrusted input.** Titles and company names come from a third party
and could contain HTML or `javascript:` URLs.

- Render all upstream strings as **text nodes only** — never `innerHTML`. This is the primary
  XSS control, and given the PAT lives on this origin, it is the control that protects the
  token.
- Sanitize outbound links: allow `https:` only; reject `javascript:`/`data:`. Use
  `rel="noopener noreferrer"`.
- Strict CSP: `default-src 'self'; connect-src 'self' https://api.github.com;
  script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`.
  This means **no CDN scripts and no inline event handlers** — a deliberate constraint that
  the frontend spec is built around.
- No analytics, no third-party fonts, no external requests beyond `api.github.com`.

## 6. Supply chain and CI

- **Pin all Actions to a commit SHA**, not a tag (`actions/checkout@<sha>`). Tags are mutable.
- Sync workflow: `permissions: contents: write` and nothing more; no `pull-requests`, no
  `id-token`.
- Zero-runtime-dependency parser (Python stdlib) — nothing to compromise via PyPI. `pytest`
  is dev-only, pinned, and never runs with repo write access in the same job as the commit.
- The sync workflow **never** checks out or executes upstream code. Upstream's `scripts/*.py`
  are *read as data* for schema understanding — **never executed.** Worth stating explicitly:
  executing a third party's auto-synced Python in our CI would be a straightforward supply
  chain compromise.
- Dependabot on Actions.

## 7. Failure and recovery

| Scenario | Result | Recovery |
| --- | --- | --- |
| Upstream schema change | CI fails, no commit | Fix parser; add fixture; last good data still served |
| Upstream deleted/renamed | Fetch fails, no commit | Our data is self-contained; repin id |
| Parser crash mid-run | No partial write (write is atomic, all-or-nothing) | Re-run; personal layer untouched by construction |
| Mass upstream deletion | Row-count floor trips, sync aborts | Manual review |
| PAT leaked | Notes disclosed; file may be vandalised | Revoke token; `git revert` in personal repo |
| PAT expired | Saves fail with a clear UI error | Issue a new token; IndexedDB cache holds unsaved state |
| Two devices edit concurrently | 409 on stale SHA | Fetch, per-ID merge, resubmit |
| Personal repo lost | Notes lost | Git history + per-device IndexedDB + periodic export |

## 8. Ratified decisions affecting this document

| # | Decision |
| --- | --- |
| D3 | Personal layer in a **private** repo; PAT scoped to it alone |
| D4 | Practice links surfaced — the outbound link is the attribution |
| D5 | **Metadata only.** Never problem statements |
| D8 | No verbatim mirror; upstream commit SHA + normalized data (pinned fixtures excepted) |
| D11 | Browser-held single-repo fine-grained PAT accepted, with §5 controls binding |
| D12 | Public Pages site, with prominent attribution |
| D13 | PAT expiry **90 days** |
| D14 | Notes stored **plaintext** in the private repo |
| D18 | Notes are **plain text**, not rendered markdown — no sanitizer in the trust path |

### Standing obligations

These are not one-time choices; they must hold for the life of the project.

1. **Never execute upstream code.** `scripts/*.py` upstream are read as documentation only.
2. **Never add a CDN or third-party script** to the site. The CSP that protects the PAT
   depends on `script-src 'self'`.
3. **Never give the sync job a credential for the personal repo.** The isolation in §1 is the
   reason a bad parse cannot destroy personal data.
4. **Never render upstream strings as HTML.** Text nodes only.
5. **Honour a takedown immediately** if the upstream maintainer objects.
