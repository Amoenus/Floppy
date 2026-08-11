# Upstream parity execution board

> **GitHub Project:** [dannyvfilms project #1](https://github.com/users/dannyvfilms/projects/1)  
> **Durable decision ledger:** [`UPSTREAM_PORTS.md`](UPSTREAM_PORTS.md)  
> **Programme issue:** [#645](https://github.com/dannyvfilms/Floppy/issues/645)  
> **Phase 0 PR:** [#651](https://github.com/dannyvfilms/Floppy/pull/651)

## Purpose

`UPSTREAM_PORTS.md` records long-lived decisions: what was reviewed, what Floppy will port, what Floppy already supersedes, what is intentionally discarded, and why.

Project #1 is the operational layer. It should show what is being reviewed or implemented now, what is blocked, and what comes next. Project status is allowed to change frequently; discard and supersession rationale must remain in Git history rather than living only in project fields.

## Initial board population

| Item | Role | Initial state | Priority | Blocked by / relationship |
|---|---|---|---|---|
| [#651](https://github.com/dannyvfilms/Floppy/pull/651) | Phase 0 decision-ledger PR | Review | P0 | None |
| [#645](https://github.com/dannyvfilms/Floppy/issues/645) | Programme index | In progress | P0 | Complete Phase 0 when #651 is merged and the board is populated |
| [#646](https://github.com/dannyvfilms/Floppy/issues/646) | Built-image smoke gate | Ready next | P0 | #651 |
| [#647](https://github.com/dannyvfilms/Floppy/issues/647) | uv project, workspace lockfile, CI and Docker | Blocked | P0 | #646 |
| [#648](https://github.com/dannyvfilms/Floppy/issues/648) | Datetime and calendar integrity | Blocked | P0 | #646; runtime semantics before migrations |
| [#649](https://github.com/dannyvfilms/Floppy/issues/649) | Provider correctness | Ready after safety baseline | P1 | #646; coordinate unknown dates with #648 |
| [#650](https://github.com/dannyvfilms/Floppy/issues/650) | Identity audit, repair and constraints | Blocked | P1 | #646 and #648 |
| [#597](https://github.com/dannyvfilms/Floppy/issues/597) | Reusable deployment preflight | Related active work | P1 | Integrate with #646 without replacing the external image test |
| [#639](https://github.com/dannyvfilms/Floppy/issues/639) | Cross-provider episode/calendar duplicate regression | Active acceptance target | P1 | Concrete user-facing target for #650; do not close from epic completion alone |
| [#390](https://github.com/dannyvfilms/Floppy/issues/390) | Existing CI/Ruff signal | Coordination evidence | P1 | #647 must preserve its chosen CI policy |
| [#512](https://github.com/dannyvfilms/Floppy/issues/512) | Low-tier performance/startup audit | Coordination evidence | P1 | Receives measurements from #646 and #647 |

Closed historical issues are evidence, not active project work, unless the project already retains completed cards for traceability.

## Recommended fields

Use existing equivalent fields instead of creating duplicates.

| Field | Suggested values | Use |
|---|---|---|
| **Status** | Triage, Review, Ready, In progress, Blocked, Done | Day-to-day execution |
| **Phase** | 0 through 8 | Roadmap grouping |
| **Decision** | Pending, In progress, Ported, Superseded, Discarded, Deferred | Mirrors the durable ledger state |
| **Priority** | P0, P1, P2, P3 | Portfolio order, not raw RICE alone |
| **Blocked by** | Issue or PR reference | Makes sequencing explicit |
| **Upstream baseline** | Reviewed Yamtrack SHA | Enables incremental future review |
| **Outcome owner** | Issue or maintainer | One owner per coherent outcome |

## Board rules

1. Review and merge the ledger before implementation begins.
2. Add accepted Pending or In-progress outcomes to the project.
3. Add active Floppy issues that serve as concrete regression or coordination targets.
4. Do not create cards for merge commits, version bumps, generated CSS/lock churn, individual Dependabot commits, or other discarded port units.
5. Do not close an active concrete bug merely because a broader work-package issue exists.
6. Keep closed historical evidence closed; link it from the ledger and owning issue.
7. Move an outcome to Done only after the ledger records the merged Floppy PR and validation evidence.
8. When a decision changes, update `UPSTREAM_PORTS.md`; a project-field change alone is insufficient.
9. After each upstream review, update the stored Yamtrack baseline and create cards only for accepted work.

## Current issue matching

### Exact or active Floppy targets

- #597 complements Yamtrack's built-image validation precedent but owns a reusable preflight command, not the release gate.
- #639 is the active cross-provider episode canonicalisation bug and remains a direct acceptance target for #650.
- #390 and #512 are active coordination surfaces for uv, CI, startup and performance measurements.

### Independently implemented or closed evidence

- #379 independently fixed Goodreads decimal ratings and therefore supersedes Yamtrack #1577.
- #30, #36 and #559 provide historical timezone/date regression evidence for #648.
- #544, #620 and #623 provide recent identity architecture and producer/lookup evidence for #650 and #639.
- #557 and #593 provide startup, migration and SQLite integrity-gate evidence for #646.
- #529 and #604 provide closed release-engineering context.

## Next executable order

1. Review and merge #651.
2. Populate Project #1 using the initial table above.
3. Implement #646.
4. Implement #647 without dependency upgrades.
5. Land isolated low-risk fixes owned by #648 and #649.
6. Complete the staged datetime, provider and identity packages.
7. Schedule deferred P2/P3 product work only after release and data-safety baselines are stable.
