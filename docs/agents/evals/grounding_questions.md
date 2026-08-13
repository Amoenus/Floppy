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

## Raw response records

Retain exactly one fenced block for every evaluator-arm delivery. Paste the complete response, including all three answers and the evaluator declaration, byte-for-byte into that block. Do not split, normalize, or place raw responses in a Markdown table. Complete the adjacent references after the run.

### E1 / Arm A complete response

- Response record: `<ID>`
- Run record: `<ID>`
- Delivery bundle: `<SHA-256>`
- Access log: `<ID or retained log path>`

```text

```

### E1 / Arm B complete response

- Response record: `<ID>`
- Run record: `<ID>`
- Delivery bundle: `<SHA-256>`
- Access log: `<ID or retained log path>`

```text

```

### E2 / Arm A complete response

- Response record: `<ID>`
- Run record: `<ID>`
- Delivery bundle: `<SHA-256>`
- Access log: `<ID or retained log path>`

```text

```

### E2 / Arm B complete response

- Response record: `<ID>`
- Run record: `<ID>`
- Delivery bundle: `<SHA-256>`
- Access log: `<ID or retained log path>`

```text

```

### E3 / Arm A complete response

- Response record: `<ID>`
- Run record: `<ID>`
- Delivery bundle: `<SHA-256>`
- Access log: `<ID or retained log path>`

```text

```

### E3 / Arm B complete response

- Response record: `<ID>`
- Run record: `<ID>`
- Delivery bundle: `<SHA-256>`
- Access log: `<ID or retained log path>`

```text

```

## Score indexes

Tables index scoring records only. Raw responses remain in the fenced records above.

### Score-packet index

Measure byte spans against the exact retained UTF-8 response, using a zero-based start offset and exclusive end offset. In each question cell, record `<start:end; returned citations; citation-validation record ID; scoring-packet ID>`. The scoring packet contains that question span with validated path citations mechanically replaced by opaque file IDs.

| Response record | Q1 span, citations, validation, packet | Q2 span, citations, validation, packet | Q3 span, citations, validation, packet |
| --- | --- | --- | --- |
| `<E1-A response ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` |
| `<E1-B response ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` |
| `<E2-A response ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` |
| `<E2-B response ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` |
| `<E3-A response ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` |
| `<E3-B response ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` | `<start:end; citations; validation ID; packet ID>` |

### Fact decisions

| Packet ID | Question | Fact ID | Scorer ID | Correct? | Citation valid? | Counts? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `<packet>` | `<Q1-Q3>` | `<fact ID>` | `<scorer>` | `<yes or no>` | `<yes or no>` | `<yes or no>` | `<brief reason>` |

### Question scores

| Packet ID | Scorer ID | Question | Score (`0`-`2`) | Contradiction? | Unsupported or invalidly cited factual statement? | Detail | Disallowed evidence? | Residual unblinding | Consensus record |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `<packet>` | `<scorer>` | `<Q1-Q3>` | `<score>` | `<yes or no>` | `<yes or no>` | `<statement and citation detail>` | `<yes or no>` | `<none, suspected, or actual; reason>` | `<ID>` |

### Paired deltas

| Evaluator ID | Question | Base score | Treatment score | Paired delta | Regressed? |
| --- | --- | --- | --- | --- | --- |
| `<E1-E3>` | `<Q1-Q3>` | `<score>` | `<score>` | `<treatment minus base>` | `<yes or no>` |

### Question medians and gates

| Question | Base median | Treatment median | Median change | Any paired regression? | Treatment median is 2? |
| --- | --- | --- | --- | --- | --- |
| Q1 | `<median>` | `<median>` | `<change>` | `<yes or no>` | `<yes or no>` |
| Q2 | `<median>` | `<median>` | `<change>` | `<yes or no>` | `<yes or no>` |
| Q3 | `<median>` | `<median>` | `<change>` | `<yes or no>` | `<yes or no>` |

| Main-pass gate | Result |
| --- | --- |
| Treatment median is 2 for Q1-Q3 | `<pass or fail>` |
| No paired evaluator-question regression | `<pass or fail>` |
| At least two evaluators improve on at least one question | `<pass or fail>` |
| Overall | `<pass or fail>` |

Do not fill any result, score, citation, timestamp, SHA, hash, or gate field until the run completes.

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
