# Repository grounding evaluation

## Purpose and scope

Use this contract to test whether shipped repository artifacts help a model retrieve three Floppy domain facts. Run it against the private repository. Do not publish repository content or raw answers outside the approved evaluation record.

This is a narrow, post-hoc retrieval evaluation. It is not broad proof of repository grounding. It does not collect runtime analytics, production telemetry, user data, or model usage data.

## Questions

Ask these questions exactly in the main qualitative pass:

1. What does `media_type_config` refer to in Floppy, and which source owns canonical media-type values?
2. What is the difference between an Item and a Consumption?
3. Which Celery queue and priority does the Reload calendar task use?

## Evidence arms

The base ref is the fetched `origin/latest` tip. The treatment ref is the implemented branch tip. Pin each to an immutable full commit SHA before building either bundle.

### Base arm allowlist

- `AGENTS.md`
- `docs/agents/media_type_integration.md`
- `README.md`

### Treatment arm allowlist

- `AGENTS.md`
- `docs/agents/media_type_integration.md`
- `README.md`
- `docs/agents/domain_model.md`
- `src/api/contracts/openapi.yaml`
- `mcp_server/README.md`

Do not include any other file. In particular, do not include raw source models, task modules, Celery settings, or other settings files. Do not follow imports, links, or references into files outside the arm allowlist. This restriction measures shipped grounding artifacts rather than source-code search.

## Run record

Create one run record for every evaluator and arm. Record actual values. Use `not exposed` when the runner does not expose a value. Use `not controllable` when the runner exposes no control for it. Do not infer or guess a value.

| Field | Required record |
| --- | --- |
| Run record ID | `<unique ID>` |
| Evaluator ID | `<E1, E2, or E3 plus runner execution ID>` |
| Scorer IDs | `<three independent scorer IDs>` |
| Start timestamp | `<actual ISO 8601 timestamp with offset>` |
| End timestamp | `<actual ISO 8601 timestamp with offset>` |
| Opaque arm alias | `<A or B>` |
| Arm delivery position | `<first or second>` |
| Full base SHA | `<40-character commit SHA>` |
| Full treatment SHA | `<40-character commit SHA>` |
| Tool and model ID | `<actual runner and model identifier>` |
| Model snapshot, version, or date | `<actual value or not exposed>` |
| Runner version | `<actual value or not exposed>` |
| Reasoning effort | `<actual value or not exposed>` |
| Seed | `<actual value, not exposed, or not controllable>` |
| Temperature | `<actual value, not exposed, or not controllable>` |
| Delivery mode | `embedded immutable line-numbered blobs` |
| Runner network controls | `<actual disabled control or not exposed>` |
| Runner tool controls | `<actual disabled control or not exposed>` |
| Network used | `<actual access-log result>` |
| Tools used | `<actual access-log result>` |
| Delivery bundle SHA-256 | `<hash of exact UTF-8 prompt bytes>` |
| Evaluator declaration present | `<yes or no>` |
| Access-log record | `<record ID or retained log path>` |

A run is invalid if the evaluator makes a tool or network call, the access log reports a call, the required declaration is absent, or zero-call isolation cannot be verified. Metadata such as temperature or seed may remain unavailable when recorded with the required literal values above.

## Pin and build immutable delivery bundles

1. Fetch `origin/latest` immediately before the run.
2. Resolve `origin/latest` and the implemented branch tip to full 40-character commit SHAs. Record the implemented branch name outside evaluator and scorer packets.
3. Confirm both commit objects are available locally.
4. Extract each allowlisted blob only from its pinned SHA. Fail if a listed blob is absent. Do not read the working tree when building a bundle.
5. Assign each file a mechanical opaque ID in allowlist order: `F01`, `F02`, and so on. Retain the ID-to-path mapping outside scorer packets.
6. Normalize each source blob by replacing CRLF and CR with LF, removing all trailing LF bytes, and adding exactly one trailing LF. Then render it exactly as `FILE <opaque-id>\n`, each source line as `<line-number>\t<content>\n`, and `END FILE <opaque-id>\n`. Do not add blank separators. Concatenate framed files in allowlist order.
7. Render the evaluator-only mapping in allowlist order as `<opaque-id>\t<path>\n`. This mapping lets the evaluator emit path citations. Keep it separate from the framed evidence and outside scorer packets. After citation validation, replace paths with their opaque IDs before building scorer packets.
8. Substitute the opaque arm alias, evaluator ID-to-path mapping, and canonical framed evidence into the exact prompt below.
9. Store the exact UTF-8 prompt bytes and their SHA-256 hash before delivery.
10. Disable evaluator tools and network. Deliver the prompt as embedded context. Do not give the evaluator a repository checkout, file tool, browser, shell, retrieval service, MCP resource, or network access.
11. Retain the runner access log and evaluator declaration.
12. After all answers return, resolve both named ref tips again. The run is invalid if either ref no longer equals its recorded SHA. Confirm the delivered prompt hash still matches the retained bytes.

Use an equivalent byte-preserving implementation when the runner does not use Git CLI. The invariant is that each delivered line comes from an allowlisted blob at the recorded full SHA.

## Opaque assignment and order

Keep the base/treatment mapping in a restricted allocation record. Do not include the mapping, branch names, refs, or SHAs in evaluator prompts or scorer packets.

Use this balanced order. Assign A and B to the two deliveries for each evaluator before bundle construction, and keep that assignment only in the restricted allocation record.

| Evaluator | First delivery | Second delivery |
| --- | --- | --- |
| E1 | base | treatment |
| E2 | treatment | base |
| E3 | base | treatment |

Start a fresh clean context for every evaluator-arm delivery. Do not carry the first answer into the second context. The aliases identify only the delivered arm for citation purposes.

## Exact evaluator system prompt

Replace only `{{ARM_ALIAS}}`, `{{EVALUATOR_ID_PATH_MAPPING}}`, and `{{CANONICAL_FRAMED_EVIDENCE}}`. Preserve all other text exactly. Do not add a user prompt with facts, hints, ref names, or prior answers.

```text
You are evaluating repository grounding for Floppy.

Opaque arm: {{ARM_ALIAS}}

Evaluator file mapping:
{{EVALUATOR_ID_PATH_MAPPING}}

All permitted repository evidence is embedded below. Use only that evidence. Do not use outside knowledge, assumptions, inference, prior answers, or any other repository content. Do not call a tool or network service.

Answer each question separately. Cite every factual statement in the exact form {{ARM_ALIAS}}:path:line. A citation is valid only when that embedded line directly supports the statement. If the embedded context does not support an answer, write exactly: Unknown from the allowed context.

Use concise, literal language.

Questions:
1. What does `media_type_config` refer to in Floppy, and which source owns canonical media-type values?
2. What is the difference between an Item and a Consumption?
3. Which Celery queue and priority does the Reload calendar task use?

After the three answers, write exactly: Evaluator declaration: I used only the embedded allowed context and made no tool or network calls.

Embedded allowed context:
{{CANONICAL_FRAMED_EVIDENCE}}
```

## Required fact checklist

A fact counts only when it is correct and has a citation to an allowed embedded line that directly supports it. Record correctness and citation validity separately.

### Question 1

- Q1-F1: The runtime registry is `app.config.MEDIA_TYPE_CONFIG`.
- Q1-F2: `app.models.choices.MediaTypes` owns the canonical media-type values.

### Question 2

- Q2-F1: An Item is the shared provider identity or work.
- Q2-F2: A Consumption is a per-user tracking record that stores status, progress, score, dates, and notes.
- Q2-F3: Separate Consumption records can relate to one Item.

### Question 3

- Q3-F1: The queue is `celery`.
- Q3-F2: It is background priority.
- Q3-F3: The numeric priority is `9`.
- Q3-F4: Reload calendar has no queue override, so default routing applies.

The checklist is an answer key derived from the current treatment artifacts. It was not preregistered before those artifacts were implemented.

## Citation rules

Use `A:path:line` or `B:path:line`, matching the delivered opaque alias. Use one citation for every factual statement. Use multiple citations when no one line supports the whole statement.

After validating each returned path citation, render its scorer-packet form as `A:<opaque-id>:line` or `B:<opaque-id>:line`. The scorer receives only this opaque form and the matching opaque framed evidence.

A citation is invalid when any of these conditions applies:

- Its alias does not match the delivered arm.
- Its path is not in that arm's allowlist.
- Its line is absent from the retained bundle.
- The cited line does not directly support the statement.
- It relies on a linked, imported, generated, or raw source file outside the bundle.
- It uses a bare path, line range, movable ref such as `HEAD` or `origin/latest`, or another citation format.

Any outside or disallowed evidence disqualifies the complete question answer. Do not repair an answer or its citations during scoring.

## Independent metadata-blinded scoring

Use three independent scorers. Do not allow an answer evaluator to score its own output.

Scoring is metadata-blinded, not fully treatment-blinded. Scorers do not receive treatment allocation, evaluator identity, delivery order, real paths, refs, or SHAs. The answer and evidence content can still reveal the arm. Each scorer must record whether content caused suspected or actual residual unblinding and explain why.

1. Assign every question span within a complete raw response a random scoring-packet ID.
2. Remove evaluator identity, delivery position, run sequence, ref names, SHAs, and the base/treatment mapping from scorer packets.
3. Validate returned path citations against the evaluator mapping, then replace each path with its opaque file ID. Give each scorer the opaque question span and canonical framed evidence that uses only opaque file IDs. Do not include the ID-to-path mapping. Shuffle packet order independently for every scorer.
4. For every fact, have each scorer record `correct: yes/no` and `citation valid: yes/no` separately. The fact counts only when both are `yes`.
5. Have each scorer record `unsupported or invalidly cited factual statement: yes/no` plus detail. Also record whether the answer contains a contradiction or disallowed evidence.
6. Have each scorer assign the question score below and record a short reason.
7. Take the majority of the three scorer decisions for each fact, each disqualifier, and the unsupported-or-invalidly-cited field. A majority `yes` for that field forces the consensus question score to `0`. Derive the remaining consensus question score from the majority decisions. This deterministic derivation resolves a three-way question-score split.
8. If evidence applicability itself remains disputed, hold a metadata-blinded scorer consensus review. Record the final decision and rationale. If the three scorers cannot agree, use a named independent adjudicator and retain that decision.

Score each question on this exact scale:

- `2`: Every required fact counts. There is no contradiction, unsupported or invalidly cited factual statement, or disallowed evidence.
- `1`: At least one but not every required fact counts. There is no contradiction, unsupported or invalidly cited factual statement, or disallowed evidence.
- `0`: No required fact counts, or the answer contains a contradiction, an unsupported or invalidly cited factual statement, or disallowed evidence. `Unknown from the allowed context.` also scores `0`.

Omitting a required fact permits `1` when at least one other fact counts. Stating a fact without a valid citation produces `0`, even when another fact counts.

## Main qualitative execution

1. Use three fresh evaluators, E1 through E3. Each evaluator answers all three questions for both arms in its assigned order.
2. Preserve each raw response exactly. Do not share responses between evaluator contexts.
3. Build metadata-blinded, shuffled scorer packets and complete independent scoring.
4. For each evaluator and question, calculate `treatment score - base score` after restoring the restricted arm mapping.
5. Calculate the median of the three evaluator scores for every question and arm. Do not average scores across questions.
6. Report every paired delta, question median, and gate outcome without filling missing results.

The main qualitative pass succeeds only when all of these conditions hold:

- The treatment median is `2` for each of the three questions.
- No paired evaluator-question delta is negative.
- At least two of the three evaluators improve on at least one question.

This three-evaluator comparison is qualitative. It does not establish statistical confidence.

## Completed main-pass run: 2026-08-14

### Common metadata and integrity

| Field | Recorded value |
| --- | --- |
| Run record ID | `grounding-20260814` |
| Full base SHA | `dbff5843b5257b1a6db38292325594595a085de8` |
| Full treatment SHA | `3486970e6520d5b356abbaec94134b7db5be65d2` |
| Implemented branch at evaluation | `codex/openapi-grounding-contracts` |
| Evaluator tool and model ID | `OpenAI Codex`; `gpt-5.6-terra` |
| Scorer tool and model ID | `OpenAI Codex`; `gpt-5.6-sol` |
| Model snapshot, version, or date | `not exposed` |
| Runner version | `codex-cli 0.147.0` for evaluators and scorers |
| Reasoning effort | `low` for evaluators and scorers |
| Evaluator seed | `not exposed`; `not controllable` |
| Temperature | `not exposed`; `not controllable` |
| Delivery mode | `embedded immutable line-numbered blobs` |
| Runner network controls | no network tool existed or was enabled |
| Runner tool controls | CLI flags disabled shell, apps, browser, computer, image, multi-agent, plugins, skills, and memory; each run used a read-only ephemeral isolated working directory |
| Network used | none; zero network events in all six evaluator event logs |
| Tools used | none; zero tool events in all six evaluator event logs |
| Ref verification | Before recording results, `origin/latest` still resolved to the full base SHA and branch `HEAD` still resolved to the full treatment SHA |
| Prompt verification | All six retained prompt byte counts and SHA-256 hashes matched `allocation.json` |

Each evaluator returned status `0`, the required declaration, and one agent-message event. Each evaluator log also contains a non-fatal runner warning that skill descriptions were shortened; it contains no repository access, tool call, or network call.

### Evaluator runs

The three valid scorer IDs for every run are `S1V-4b16e4`, `S2V-cd18df`, and `S3V-bf1c59`.

| Run | Evaluator and execution ID | Arm | Position | Evaluated SHA | Start | End | Prompt bytes | Prompt SHA-256 | Status | Access verification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `E1-A` | `E1`; `019ffd92-16db-7d71-92fd-f399cad3a454` | A = base | first | `dbff5843b5257b1a6db38292325594595a085de8` | `2026-08-14T01:00:37+01:00` | `2026-08-14T01:00:43+01:00` | `69391` | `e4477eae178c2ca6565b8291b48396c7198050e80ed5cfdc0a366e133701e71f` | `0` | zero tool/network events; declaration present |
| `E1-B` | `E1`; `019ffd92-6ac5-74c2-811d-f8b0979aaa22` | B = treatment | second | `3486970e6520d5b356abbaec94134b7db5be65d2` | `2026-08-14T01:00:58+01:00` | `2026-08-14T01:01:06+01:00` | `166333` | `7ccb9ab53968217e97ce343460ab82f2fe03cb524a30f9c009c7f33c5a426055` | `0` | zero tool/network events; declaration present |
| `E2-A` | `E2`; `019ffd92-16e1-76e3-8935-bf21709a569d` | A = treatment | first | `3486970e6520d5b356abbaec94134b7db5be65d2` | `2026-08-14T01:00:37+01:00` | `2026-08-14T01:00:44+01:00` | `166333` | `ad569706f9083d4ddba72140bb1d5272b29011bbad5606d285d8c65b0b954369` | `0` | zero tool/network events; declaration present |
| `E2-B` | `E2`; `019ffd92-6ab9-7df3-b5fd-a5203fff1d77` | B = base | second | `dbff5843b5257b1a6db38292325594595a085de8` | `2026-08-14T01:00:58+01:00` | `2026-08-14T01:01:05+01:00` | `69391` | `4f73d9ef3488817d756fe6a64d495da81e0ea1a1638d394876cd21dfc784b356` | `0` | zero tool/network events; declaration present |
| `E3-A` | `E3`; `019ffd92-16dd-7560-97bf-1aff2c53df16` | A = base | first | `dbff5843b5257b1a6db38292325594595a085de8` | `2026-08-14T01:00:37+01:00` | `2026-08-14T01:00:44+01:00` | `69391` | `e4477eae178c2ca6565b8291b48396c7198050e80ed5cfdc0a366e133701e71f` | `0` | zero tool/network events; declaration present |
| `E3-B` | `E3`; `019ffd92-6ab9-7ee1-9291-b3a0e6f90955` | B = treatment | second | `3486970e6520d5b356abbaec94134b7db5be65d2` | `2026-08-14T01:00:58+01:00` | `2026-08-14T01:01:05+01:00` | `166333` | `7ccb9ab53968217e97ce343460ab82f2fe03cb524a30f9c009c7f33c5a426055` | `0` | zero tool/network events; declaration present |

### Valid scoring runs

| Scorer ID and execution ID | Start | End | Shuffle seed | Prompt SHA-256 | Status | Access verification |
| --- | --- | --- | --- | --- | --- | --- |
| `S1V-4b16e4`; `019ffd97-d38f-7210-be78-8acf0e30592c` | `2026-08-14T01:06:53+01:00` | `2026-08-14T01:08:21+01:00` | `1463324940316341645` | `c1c9f5967f0e649e7f430ebe64f1aad08cd5c2a03c7e0c3968e470a9ec438a31` | `0` | prompt hash matched; zero tool/network events |
| `S2V-cd18df`; `019ffd97-d392-7a23-9a9b-370bf1f73152` | `2026-08-14T01:06:53+01:00` | `2026-08-14T01:08:17+01:00` | `12183961628636262223` | `0dbec0ad7fe346e730f7651c0cba204dceb92de96b118c278e399d706cddc374` | `0` | prompt hash matched; zero tool/network events |
| `S3V-bf1c59`; `019ffd97-d38f-71d2-8d72-edb729e219fd` | `2026-08-14T01:06:53+01:00` | `2026-08-14T01:08:21+01:00` | `7081352488126536805` | `ce994c22f38b8d49d137a6807380db4f08034d9f4ce436760023f11d86c8d9d5` | `0` | prompt hash matched; zero tool/network events |

### Protocol deviation and remediation

The first scorer run under `scorers/` is excluded because its packets omitted the citation alias declared by each answer. None of its scores are used. The remediation rebuilt packets with the declared aliases and reran three independent scorers under `scorers-valid/`; only those three results contribute to the fact votes and consensus scores below. Evaluator prompts and raw responses did not change.

## Raw response records

Retain exactly one fenced block for every evaluator-arm delivery. Paste the complete response, including all three answers and the evaluator declaration, byte-for-byte into that block. Do not split, normalize, or place raw responses in a Markdown table. The retained raw files have no trailing LF. The LF that places each closing fence on its own line is Markdown framing and is excluded from the recorded raw byte count and SHA-256.

### E1 / Arm A complete response

- Response record: `R-E1-A`; `480` bytes; SHA-256 `35c224798d4a39008b311a81af9831fb083b30ca489e31d8bd925737a3acef2a`
- Run record: `E1-A`
- Delivery bundle: `e4477eae178c2ca6565b8291b48396c7198050e80ed5cfdc0a366e133701e71f`
- Access log: `.gstack/evals/grounding-20260814/runs/E1-A/events.jsonl`; zero tool/network events
- Score packets: `P-a1c0248c`, `P-2b915145`, `P-3b09f212`

```text
1. `media_type_config` supplies per-media-type properties for UI and logic. `MediaTypes` in `src/app/models.py` owns valid canonical `media_type` values. A:docs/agents/media_type_integration.md:6 A:docs/agents/media_type_integration.md:7

2. An `Item` holds shared media identity fields. A Consumption is not described in the allowed context.

3. Unknown from the allowed context.

Evaluator declaration: I used only the embedded allowed context and made no tool or network calls.
```

### E1 / Arm B complete response

- Response record: `R-E1-B`; `737` bytes; SHA-256 `a2938472b3c19ddf834a4626e25852bfdc4ac16058a214fada1735d5e2fc71df`
- Run record: `E1-B`
- Delivery bundle: `7ccb9ab53968217e97ce343460ab82f2fe03cb524a30f9c009c7f33c5a426055`
- Access log: `.gstack/evals/grounding-20260814/runs/E1-B/events.jsonl`; zero tool/network events
- Score packets: `P-d1a871bd`, `P-cd894e8f`, `P-f92abd73`

```text
1. `media_type_config` refers to the runtime registry `app.config.MEDIA_TYPE_CONFIG`, which supplies per-type properties for UI and logic. Canonical media-type values are owned by `app.models.choices.MediaTypes`. B:docs/agents/media_type_integration.md:6 B:docs/agents/media_type_integration.md:7

2. An Item is a shared provider-identified work. A Consumption is one user’s tracking record for an Item, storing status, progress, score, dates, and notes. B:docs/agents/domain_model.md:9 B:docs/agents/domain_model.md:23

3. The Reload calendar task uses the `celery` queue with background priority `9`. B:docs/agents/domain_model.md:45

Evaluator declaration: I used only the embedded allowed context and made no tool or network calls.
```

### E2 / Arm A complete response

- Response record: `R-E2-A`; `624` bytes; SHA-256 `178ccf82363925a55627fb66ef632515f0cbc1d7c593810dc3d36b75caec1b1c`
- Run record: `E2-A`
- Delivery bundle: `ad569706f9083d4ddba72140bb1d5272b29011bbad5606d285d8c65b0b954369`
- Access log: `.gstack/evals/grounding-20260814/runs/E2-A/events.jsonl`; zero tool/network events
- Score packets: `P-5009bbd4`, `P-0055a4e4`, `P-b6a1edd1`

```text
1. `media_type_config` is not identified in the allowed context. Canonical media-type values come from `app.models.choices.MediaTypes`. A:docs/agents/domain_model.md:34

2. An Item is a shared work identified from a media provider. A:docs/agents/domain_model.md:9 A Consumption is one user’s tracking record for that Item, storing status, progress, score, dates, and notes. A:docs/agents/domain_model.md:23

3. The Reload calendar task uses the `celery` queue with background priority `9`. A:docs/agents/domain_model.md:45

Evaluator declaration: I used only the embedded allowed context and made no tool or network calls.
```

### E2 / Arm B complete response

- Response record: `R-E2-B`; `388` bytes; SHA-256 `5117b67c81d2a892f044a2f489b246a9e48621c6c722f236bf87b833f3fb5d29`
- Run record: `E2-B`
- Delivery bundle: `4f73d9ef3488817d756fe6a64d495da81e0ea1a1638d394876cd21dfc784b356`
- Access log: `.gstack/evals/grounding-20260814/runs/E2-B/events.jsonl`; zero tool/network events
- Score packets: `P-7e1f0cff`, `P-85035d93`, `P-823c8344`

```text
1. `media_type_config` supplies per-type properties used by UI and logic. `MediaTypes` owns valid canonical `media_type` values. B:docs/agents/media_type_integration.md:6 B:docs/agents/media_type_integration.md:7

2. Unknown from the allowed context.

3. Unknown from the allowed context.

Evaluator declaration: I used only the embedded allowed context and made no tool or network calls.
```

### E3 / Arm A complete response

- Response record: `R-E3-A`; `735` bytes; SHA-256 `6d987d2f5c5b84dc471f737efef217cf635aa051e7bedb9521637ab0fe3432da`
- Run record: `E3-A`
- Delivery bundle: `e4477eae178c2ca6565b8291b48396c7198050e80ed5cfdc0a366e133701e71f`
- Access log: `.gstack/evals/grounding-20260814/runs/E3-A/events.jsonl`; zero tool/network events
- Score packets: `P-5e05ea3f`, `P-e447783e`, `P-b2de742f`

```text
1. `media_type_config` is `src/app/media_type_config.py`, which supplies per-type properties for UI and logic. `MediaTypes` and `Sources` in `src/app/models.py` govern valid canonical `media_type` and `source` values. A:docs/agents/media_type_integration.md:6 A:docs/agents/media_type_integration.md:7

2. An `Item` holds shared media identity fields. A `Media` tracking model holds per-user history, score, progress, status, dates, and notes. The term “Consumption” is not supported by the allowed context. A:docs/agents/media_type_integration.md:11 A:docs/agents/media_type_integration.md:12

3. Unknown from the allowed context.

Evaluator declaration: I used only the embedded allowed context and made no tool or network calls.
```

### E3 / Arm B complete response

- Response record: `R-E3-B`; `772` bytes; SHA-256 `df6e0df192663eb881c7e93bbca1d037ec94fac6824c147118d649667c3db38b`
- Run record: `E3-B`
- Delivery bundle: `7ccb9ab53968217e97ce343460ab82f2fe03cb524a30f9c009c7f33c5a426055`
- Access log: `.gstack/evals/grounding-20260814/runs/E3-B/events.jsonl`; zero tool/network events
- Score packets: `P-72d99220`, `P-7ab3a7d7`, `P-f8b95247`

```text
1. `media_type_config` refers to the runtime registry `app.config.MEDIA_TYPE_CONFIG`, which supplies per-type properties used by UI and logic. Canonical media-type values are owned by `app.models.choices.MediaTypes`. B:docs/agents/media_type_integration.md:6-7

2. An Item is the shared provider-identified work; different users can track it through separate Consumption records. A Consumption is one user’s tracking record for an Item and stores status, progress, score, dates, and notes. B:docs/agents/domain_model.md:9 B:docs/agents/domain_model.md:23

3. The Reload calendar task uses the `celery` queue with background priority `9`. B:docs/agents/domain_model.md:45

Evaluator declaration: I used only the embedded allowed context and made no tool or network calls.
```

## Score indexes

Tables index scoring records only. Raw responses remain in the fenced records above.

### Score-packet index

Measure byte spans against the exact retained UTF-8 response, using a zero-based start offset and exclusive end offset. In each question cell, record `<start:end; returned citations; citation-validation record ID; scoring-packet ID>`. The scoring packet contains that question span with validated path citations mechanically replaced by opaque file IDs.

| Response record | Q1 span, citations, validation, packet | Q2 span, citations, validation, packet | Q3 span, citations, validation, packet |
| --- | --- | --- | --- |
| `R-E1-A` | `0:239`; A:docs/agents/media_type_integration.md:6<br>A:docs/agents/media_type_integration.md:7; `V-f525fe38`; `P-a1c0248c` | `239:344`; none; `V-1fe3f515`; `P-2b915145` | `344:382`; none; `V-28da33a2`; `P-3b09f212` |
| `R-E1-B` | `0:298`; B:docs/agents/media_type_integration.md:6<br>B:docs/agents/media_type_integration.md:7; `V-57e79a17`; `P-d1a871bd` | `298:523`; B:docs/agents/domain_model.md:9<br>B:docs/agents/domain_model.md:23; `V-6151139d`; `P-cd894e8f` | `523:639`; B:docs/agents/domain_model.md:45; `V-254850f8`; `P-f92abd73` |
| `R-E2-A` | `0:170`; A:docs/agents/domain_model.md:34; `V-425020d0`; `P-5009bbd4` | `170:410`; A:docs/agents/domain_model.md:9<br>A:docs/agents/domain_model.md:23; `V-4a27857f`; `P-0055a4e4` | `410:526`; A:docs/agents/domain_model.md:45; `V-030e72a1`; `P-b6a1edd1` |
| `R-E2-B` | `0:214`; B:docs/agents/media_type_integration.md:6<br>B:docs/agents/media_type_integration.md:7; `V-9e8f2770`; `P-7e1f0cff` | `214:252`; none; `V-8704b764`; `P-85035d93` | `252:290`; none; `V-8fdcf6de`; `P-823c8344` |
| `R-E3-A` | `0:303`; A:docs/agents/media_type_integration.md:6<br>A:docs/agents/media_type_integration.md:7; `V-b105a9d0`; `P-5e05ea3f` | `303:599`; A:docs/agents/media_type_integration.md:11<br>A:docs/agents/media_type_integration.md:12; `V-099b579a`; `P-e447783e` | `599:637`; none; `V-a56bb46f`; `P-b2de742f` |
| `R-E3-B` | `0:262`; B:docs/agents/media_type_integration.md:6-7; `V-dc8db630`; `P-72d99220` | `262:558`; B:docs/agents/domain_model.md:9<br>B:docs/agents/domain_model.md:23; `V-5ee0a417`; `P-7ab3a7d7` | `558:674`; B:docs/agents/domain_model.md:45; `V-13523d19`; `P-f8b95247` |

### Fact decisions

Each ratio is the number of `yes` decisions among the three valid scorers. A fact counts only when both majority decisions are `yes`.

| Run | Packet | Fact | Correct majority | Citation-valid majority | Counts? |
| --- | --- | --- | --- | --- | --- |
| `E1-A` | `P-a1c0248c` | `Q1-F1` | no (`0/3`) | no (`1/3`) | no |
| `E1-A` | `P-a1c0248c` | `Q1-F2` | no (`0/3`) | yes (`2/3`) | no |
| `E1-A` | `P-2b915145` | `Q2-F1` | yes (`3/3`) | no (`0/3`) | no |
| `E1-A` | `P-2b915145` | `Q2-F2` | no (`0/3`) | no (`0/3`) | no |
| `E1-A` | `P-2b915145` | `Q2-F3` | no (`0/3`) | no (`0/3`) | no |
| `E1-A` | `P-3b09f212` | `Q3-F1` | no (`0/3`) | no (`0/3`) | no |
| `E1-A` | `P-3b09f212` | `Q3-F2` | no (`0/3`) | no (`0/3`) | no |
| `E1-A` | `P-3b09f212` | `Q3-F3` | no (`0/3`) | no (`0/3`) | no |
| `E1-A` | `P-3b09f212` | `Q3-F4` | no (`0/3`) | no (`0/3`) | no |
| `E1-B` | `P-d1a871bd` | `Q1-F1` | yes (`3/3`) | yes (`3/3`) | yes |
| `E1-B` | `P-d1a871bd` | `Q1-F2` | yes (`3/3`) | yes (`3/3`) | yes |
| `E1-B` | `P-cd894e8f` | `Q2-F1` | yes (`3/3`) | yes (`3/3`) | yes |
| `E1-B` | `P-cd894e8f` | `Q2-F2` | yes (`3/3`) | yes (`3/3`) | yes |
| `E1-B` | `P-cd894e8f` | `Q2-F3` | no (`0/3`) | no (`0/3`) | no |
| `E1-B` | `P-f92abd73` | `Q3-F1` | yes (`3/3`) | yes (`3/3`) | yes |
| `E1-B` | `P-f92abd73` | `Q3-F2` | yes (`3/3`) | yes (`3/3`) | yes |
| `E1-B` | `P-f92abd73` | `Q3-F3` | yes (`3/3`) | yes (`3/3`) | yes |
| `E1-B` | `P-f92abd73` | `Q3-F4` | no (`0/3`) | no (`0/3`) | no |
| `E2-A` | `P-5009bbd4` | `Q1-F1` | no (`0/3`) | no (`0/3`) | no |
| `E2-A` | `P-5009bbd4` | `Q1-F2` | yes (`3/3`) | yes (`3/3`) | yes |
| `E2-A` | `P-0055a4e4` | `Q2-F1` | yes (`3/3`) | yes (`3/3`) | yes |
| `E2-A` | `P-0055a4e4` | `Q2-F2` | yes (`3/3`) | yes (`3/3`) | yes |
| `E2-A` | `P-0055a4e4` | `Q2-F3` | no (`0/3`) | no (`0/3`) | no |
| `E2-A` | `P-b6a1edd1` | `Q3-F1` | yes (`3/3`) | yes (`3/3`) | yes |
| `E2-A` | `P-b6a1edd1` | `Q3-F2` | yes (`3/3`) | yes (`3/3`) | yes |
| `E2-A` | `P-b6a1edd1` | `Q3-F3` | yes (`3/3`) | yes (`3/3`) | yes |
| `E2-A` | `P-b6a1edd1` | `Q3-F4` | no (`0/3`) | no (`0/3`) | no |
| `E2-B` | `P-7e1f0cff` | `Q1-F1` | no (`0/3`) | no (`1/3`) | no |
| `E2-B` | `P-7e1f0cff` | `Q1-F2` | no (`1/3`) | yes (`2/3`) | no |
| `E2-B` | `P-85035d93` | `Q2-F1` | no (`0/3`) | no (`0/3`) | no |
| `E2-B` | `P-85035d93` | `Q2-F2` | no (`0/3`) | no (`0/3`) | no |
| `E2-B` | `P-85035d93` | `Q2-F3` | no (`0/3`) | no (`0/3`) | no |
| `E2-B` | `P-823c8344` | `Q3-F1` | no (`0/3`) | no (`0/3`) | no |
| `E2-B` | `P-823c8344` | `Q3-F2` | no (`0/3`) | no (`0/3`) | no |
| `E2-B` | `P-823c8344` | `Q3-F3` | no (`0/3`) | no (`0/3`) | no |
| `E2-B` | `P-823c8344` | `Q3-F4` | no (`0/3`) | no (`0/3`) | no |
| `E3-A` | `P-5e05ea3f` | `Q1-F1` | no (`0/3`) | yes (`3/3`) | no |
| `E3-A` | `P-5e05ea3f` | `Q1-F2` | no (`0/3`) | yes (`3/3`) | no |
| `E3-A` | `P-e447783e` | `Q2-F1` | yes (`3/3`) | yes (`3/3`) | yes |
| `E3-A` | `P-e447783e` | `Q2-F2` | no (`0/3`) | no (`1/3`) | no |
| `E3-A` | `P-e447783e` | `Q2-F3` | no (`0/3`) | no (`0/3`) | no |
| `E3-A` | `P-b2de742f` | `Q3-F1` | no (`0/3`) | no (`0/3`) | no |
| `E3-A` | `P-b2de742f` | `Q3-F2` | no (`0/3`) | no (`0/3`) | no |
| `E3-A` | `P-b2de742f` | `Q3-F3` | no (`0/3`) | no (`0/3`) | no |
| `E3-A` | `P-b2de742f` | `Q3-F4` | no (`0/3`) | no (`0/3`) | no |
| `E3-B` | `P-72d99220` | `Q1-F1` | yes (`3/3`) | no (`0/3`) | no |
| `E3-B` | `P-72d99220` | `Q1-F2` | yes (`3/3`) | no (`0/3`) | no |
| `E3-B` | `P-7ab3a7d7` | `Q2-F1` | yes (`3/3`) | yes (`3/3`) | yes |
| `E3-B` | `P-7ab3a7d7` | `Q2-F2` | yes (`3/3`) | yes (`3/3`) | yes |
| `E3-B` | `P-7ab3a7d7` | `Q2-F3` | yes (`3/3`) | yes (`3/3`) | yes |
| `E3-B` | `P-f8b95247` | `Q3-F1` | yes (`3/3`) | yes (`3/3`) | yes |
| `E3-B` | `P-f8b95247` | `Q3-F2` | yes (`3/3`) | yes (`3/3`) | yes |
| `E3-B` | `P-f8b95247` | `Q3-F3` | yes (`3/3`) | yes (`3/3`) | yes |
| `E3-B` | `P-f8b95247` | `Q3-F4` | no (`0/3`) | no (`0/3`) | no |

### Question scores

All three valid scorers assigned the same score to every packet. Ratios in the disqualifier columns are `yes` votes.

| Run | Packet | Question | Consensus score | Contradiction | Unsupported or invalidly cited statement | Disallowed evidence | Residual unblinding |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `E1-A` | `P-a1c0248c` | Q1 | `0` (`3/3`) | no (`1/3`) | yes (`2/3`) | no (`0/3`) | actual (`3/3`) |
| `E1-A` | `P-2b915145` | Q2 | `0` (`3/3`) | no (`0/3`) | yes (`3/3`) | no (`0/3`) | actual (`3/3`) |
| `E1-A` | `P-3b09f212` | Q3 | `0` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E1-B` | `P-d1a871bd` | Q1 | `2` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E1-B` | `P-cd894e8f` | Q2 | `1` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E1-B` | `P-f92abd73` | Q3 | `1` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E2-A` | `P-5009bbd4` | Q1 | `0` (`3/3`) | yes (`3/3`) | yes (`3/3`) | no (`0/3`) | actual (`3/3`) |
| `E2-A` | `P-0055a4e4` | Q2 | `1` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E2-A` | `P-b6a1edd1` | Q3 | `1` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E2-B` | `P-7e1f0cff` | Q1 | `0` (`3/3`) | no (`0/3`) | yes (`2/3`) | no (`0/3`) | actual (`3/3`) |
| `E2-B` | `P-85035d93` | Q2 | `0` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E2-B` | `P-823c8344` | Q3 | `0` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E3-A` | `P-5e05ea3f` | Q1 | `0` (`3/3`) | yes (`3/3`) | no (`1/3`) | no (`0/3`) | actual (`3/3`) |
| `E3-A` | `P-e447783e` | Q2 | `0` (`3/3`) | yes (`2/3`) | yes (`2/3`) | no (`0/3`) | actual (`3/3`) |
| `E3-A` | `P-b2de742f` | Q3 | `0` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E3-B` | `P-72d99220` | Q1 | `0` (`3/3`) | no (`0/3`) | yes (`3/3`) | no (`0/3`) | actual (`3/3`) |
| `E3-B` | `P-7ab3a7d7` | Q2 | `2` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |
| `E3-B` | `P-f8b95247` | Q3 | `1` (`3/3`) | no (`0/3`) | no (`0/3`) | no (`0/3`) | actual (`3/3`) |

### Paired deltas

| Evaluator ID | Question | Base score | Treatment score | Paired delta | Regressed? |
| --- | --- | --- | --- | --- | --- |
| E1 | Q1 | `0` | `2` | `+2` | no |
| E1 | Q2 | `0` | `1` | `+1` | no |
| E1 | Q3 | `0` | `1` | `+1` | no |
| E2 | Q1 | `0` | `0` | `0` | no |
| E2 | Q2 | `0` | `1` | `+1` | no |
| E2 | Q3 | `0` | `1` | `+1` | no |
| E3 | Q1 | `0` | `0` | `0` | no |
| E3 | Q2 | `0` | `2` | `+2` | no |
| E3 | Q3 | `0` | `1` | `+1` | no |

### Question medians and gates

| Question | Base median | Treatment median | Median change | Any paired regression? | Treatment median is 2? |
| --- | --- | --- | --- | --- | --- |
| Q1 | `0` | `0` | `0` | no | no |
| Q2 | `0` | `1` | `+1` | no | no |
| Q3 | `0` | `1` | `+1` | no | no |

| Main-pass gate | Result |
| --- | --- |
| Treatment median is 2 for Q1-Q3 | fail; medians are Q1 `0`, Q2 `1`, Q3 `1` |
| No paired evaluator-question regression | pass |
| At least two evaluators improve on at least one question | pass; all three improve |
| Overall | **fail** |

The strict evaluation fails because treatment did not reach median `2` on all questions. This is a failure of the defined retrieval-and-citation gate, not evidence that the implementation or its documented facts are incorrect.

## Current conditional-workstream decision

No candidate run exists, and neither workstream has the required named candidate artifact and optional access path. The current decision is therefore `DEFER` for both workstreams. This is a protocol-readiness decision, not an evaluation result.

| Workstream | Current decision | Candidate run | Missing prerequisite |
| --- | --- | --- | --- |
| W2 JSON-LD | `DEFER` | none | Named JSON-LD artifact and optional MCP resource access documentation |
| W3 AsyncAPI | `DEFER` | none | Named AsyncAPI or channel-registry artifact and optional access documentation |

## Future candidate protocol

Preregister each candidate before candidate artifact implementation. The preregistration must pin the implemented-without-candidate control SHA, name the target question, freeze the exact candidate allowlist and access path, define the fact checklist, and hash the prompt and question set.

Use an independent author who does not implement the candidate artifact to write held-out paraphrases of the target question. Freeze and hash those paraphrases before implementation. Withhold them from artifact authors until the candidate SHA is pinned. Record authorship and preregistration timestamps.

### W2 JSON-LD candidate

- Target question: Q2.
- Control: the pinned implemented branch without the candidate artifact, not `origin/latest`.
- Candidate optional context: a preregistered, named JSON-LD artifact and the document that names its optional MCP resource access path.
- Required access record: the exact repository path, MCP resource name or URI, and proof that runtime operation does not depend on the optional resource.

### W3 AsyncAPI candidate

- Target question: Q3.
- Control: the pinned implemented branch without the candidate artifact, not `origin/latest`.
- Candidate optional context: a preregistered, named AsyncAPI artifact or channel registry and its access documentation.
- Required evidence: verified event or channel facts beyond repetition of the vocabulary guide or OpenAPI artifact.

For either workstream, run the control and candidate arms with the same immutable-blob delivery, exact prompt rules, arm-order balancing, three fresh evaluators, three metadata-blinded scorers, fact checklist, raw-response retention, and consensus procedure used in the main pass. Evaluators must receive only the preregistered allowlist. Do not give a candidate arm runtime MCP or network access; evaluate the named optional access documentation as an embedded pinned blob.

A future candidate may proceed only when all of these gates pass on both the exact target question and its preregistered held-out paraphrases:

- The candidate target median improves by at least `1` over the implemented-without-candidate control.
- At least two of three paired evaluators improve on the target.
- No individual evaluator score regresses on any question.
- No question median regresses.
- Every required fact in every candidate answer has a valid citation.
- The candidate has a named optional access path.

If the implemented control median is already `2`, the required median improvement is impossible and the workstream remains deferred. If any gate fails or any prerequisite was defined after implementation, defer the workstream.

| Candidate | Preregistered control SHA | Target | Artifact | Named optional access path | Held-out set hash | Run status | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| W2 | `<full SHA>` | Q2 | `<path>` | `<path or resource URI>` | `<SHA-256>` | `<not run or complete>` | `<proceed or defer>` |
| W3 | `<full SHA>` | Q3 | `<path>` | `<path or resource URI>` | `<SHA-256>` | `<not run or complete>` | `<proceed or defer>` |

## Limitations

- Model and runner behavior can drift between runs.
- Temperature, seed, snapshot, reasoning effort, or runner version may not be exposed or controllable.
- Three evaluator runs are a qualitative sample and do not provide statistical confidence.
- The questions and evidence are repository-specific.
- The answer key mirrors current treatment artifacts and was not preregistered before treatment implementation.
- This narrow post-hoc retrieval test does not prove broad repository grounding.
- The evaluation is not production telemetry or runtime analytics.
