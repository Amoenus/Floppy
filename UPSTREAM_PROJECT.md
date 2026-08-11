# Upstream resolution execution board

> **GitHub Project:** [dannyvfilms project #1](https://github.com/users/dannyvfilms/projects/1)
> **Durable decision ledger:** [`UPSTREAM_PORTS.md`](UPSTREAM_PORTS.md)
> **Programme issue:** [#645](https://github.com/dannyvfilms/Floppy/issues/645)
> **Phase 0 PR:** [#651](https://github.com/dannyvfilms/Floppy/pull/651)

## Purpose

The ledger records durable decisions and evidence. Project #1 is the changing operational view: what is being reviewed or implemented, what is blocked, and what comes next. A project-field change never replaces a ledger update.

**Current live state (2026-08-11): population is outstanding.** Project #1 contains 17 draft upstream-review cards and none of #645–#653 or the coordination items below. The table prescribes the required population; it does not describe current board membership.

Phase 0 is complete only when PR #651 is merged and this population is actually added and verified. Runtime packages do not begin from an unmerged draft ledger unless #645 records a narrow exception.

## Required population (outstanding)

| Item | Role | Required Status | Priority | Dependency or relationship |
|---|---|---|---|---|
| [#651](https://github.com/dannyvfilms/Floppy/pull/651) | Exhaustive decision ledger and governance | In review | P0 | Merge gate for Phase 0 |
| [#645](https://github.com/dannyvfilms/Floppy/issues/645) | Programme index | In progress | P0 | Done after #651 merges and this board is populated |
| [#646](https://github.com/dannyvfilms/Floppy/issues/646) | Built-image smoke gate | Ready | P0 | #651 |
| [#647](https://github.com/dannyvfilms/Floppy/issues/647) | uv, lockfile, CI, lint, and Docker | Backlog | P0 | #646; no dependency upgrades during conversion |
| [#648](https://github.com/dannyvfilms/Floppy/issues/648) | Datetime/calendar integrity and import-date fixes | Backlog | P0 | #646; final runtime semantics before migrations |
| [#649](https://github.com/dannyvfilms/Floppy/issues/649) | MAL, AniList, and Open Library correctness | Backlog | P1 | #646; coordinate unknown dates with #648 |
| [#650](https://github.com/dannyvfilms/Floppy/issues/650) | Identity audit, repair, and constraints | Backlog | P1 | #646 and #648 |
| [#653](https://github.com/dannyvfilms/Floppy/pull/653) | Restore first-run query-budget signal | In review | P0 | Narrow Phase 0 exception recorded on #645; not an upstream runtime port |
| [#597](https://github.com/dannyvfilms/Floppy/issues/597) | Reusable deployment preflight | In progress | P1 | Complements #646; does not replace external image validation |
| [#639](https://github.com/dannyvfilms/Floppy/issues/639) | Cross-provider episode/calendar duplicate regression | In progress | P1 | Concrete target for #650; do not close from epic completion alone |
| [#390](https://github.com/dannyvfilms/Floppy/issues/390) | Existing CI/Ruff signal | Backlog | P1 | #647 preserves or deliberately replaces its chosen policy |
| [#512](https://github.com/dannyvfilms/Floppy/issues/512) | Low-tier performance/startup audit | Backlog | P1 | Receives measurements from #646 and #647 |

PR [#638](https://github.com/dannyvfilms/Floppy/pull/638) remains historical/open work unless separately closed. Its merge/cherry-pick convergence strategy is superseded by semantic resolution and must not be used as the programme implementation path.

Closed issues remain evidence rather than active cards unless the project deliberately retains completed cards for traceability. Relevant examples include #30, #36, #246, #295, #379, #529, #557, #559, #593, #604, #620, and #623.

## Project fields

### Existing live fields

| Field | Values | Purpose |
|---|---|---|
| **Status** | Backlog, Ready, In progress, In review, Done | Day-to-day execution |
| **Priority** | P0, P1, P2 | Portfolio order; P3 remains ledger-only unless the field is expanded |

### Proposed fields to add

These fields do not currently exist on Project #1.

| Field | Proposed values | Purpose |
|---|---|---|
| **Phase** | 0 through 6 | Package grouping from the ledger |
| **Decision** | Pending, Ported, Adapted, Superseded, Deferred, Discarded | Mirrors the durable ledger |
| **Blocked by** | Issue or PR reference | Explicit sequencing |
| **Upstream baseline** | Reviewed Yamtrack SHA | Incremental comparison boundary |
| **Outcome owner** | One issue or maintainer | Accountability for each accepted outcome |

## Board rules

1. Add accepted Pending outcomes and active Floppy regression/coordination targets.
2. Do not create cards for merge commits, release bumps, generated churn, discarded implementations, or individual dependency-bot commits.
3. Do not close a concrete bug because a broader package exists.
4. Move work to Done only after the ledger records the merged Floppy PR and validation evidence.
5. When a decision changes, update `UPSTREAM_PORTS.md`; project state alone is not durable evidence.
6. After each upstream review, update the Yamtrack baseline and add cards only for accepted work.

## Pull request topology

Use GitHub's native [stacked pull requests](https://docs.github.com/en/pull-requests/how-tos/stacked-pull-requests), currently a public preview, through GitHub's official `gh stack` extension only for genuine code dependencies. Do not create a stack merely to couple reviews of otherwise independent work.

- Keep every stack in the Floppy repository. The bottom pull request targets `latest`; each higher pull request targets the branch immediately below it. Every layer must satisfy the same branch rules and CI gates.
- Merge bottom-up, either one layer at a time or as a contiguous group starting at the lowest unmerged layer. Use the supported cascading rebase and automatic retargeting when lower layers change or merge.
- Keep stacks short and reviewable: the default maximum is three layers unless a documented dependency requires more.
- PRs [#651](https://github.com/dannyvfilms/Floppy/pull/651), [#653](https://github.com/dannyvfilms/Floppy/pull/653), and [#654](https://github.com/dannyvfilms/Floppy/pull/654) remain independent because none has a code dependency on another.
- Candidate stacks are #646 smoke gate -> the dependent #647 uv/Docker adaptation; #648 runtime semantics -> read-only audit -> migrations; and #650 audit -> repair -> constraint. MAL and Open Library fixes remain independent; AniList may stack on the #648 unknown-date layer when it depends on those semantics.
- Each layer still requires the user's separate merge authorization. Never use a stack to merge Yamtrack history, and never merge a contiguous group unless every included layer has been authorized.

## Execution order

1. Review and merge #651, then verify the initial Project #1 population.
2. Complete #646.
3. Complete #647 without dependency upgrades.
4. Land isolated correctness fixes within #648 and #649, then their larger staged packages.
5. Complete the audit/repair/constraint sequence in #650.
6. Create focused issues for deferred product work only when its ledger trigger fires.
