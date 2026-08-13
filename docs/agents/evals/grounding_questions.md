# Repository grounding evaluation

## Purpose and scope

Use this contract to measure whether shipped repository-grounding artifacts help an evaluator answer three Floppy domain questions.

Run this evaluation against the private repository. Do not publish repository content or raw answers outside the approved evaluation record. This evaluation measures documentation and contract grounding only. It does not collect runtime analytics, production telemetry, user data, or model usage data.

## Run metadata

Record these fields before scoring:

| Field | Required value |
| --- | --- |
| Run date | `2026-08-14` |
| Model and tool | `OpenAI Codex (GPT-5)` |
| Temperature | `Not exposed or controlled by the runner; no temperature claim is made.` |
| Baseline reference | `origin/latest` |
| Baseline evaluated SHA | `<record the resolved SHA>` |
| Implemented reference | current implemented branch at `HEAD` |
| Implemented branch name | `<record the branch name>` |
| Implemented evaluated SHA | `<record the resolved SHA>` |
| Evaluator IDs | `<record three unique evaluator IDs>` |

Resolve and record both SHAs immediately before the run. Do not reuse results after either ref changes.

## Questions

Ask these questions exactly:

1. What does `media_type_config` refer to in Floppy, and which source owns canonical media-type values?
2. What is the difference between an Item and a Consumption?
3. Which Celery queue and priority does the Reload calendar task use?

## Allowed context

### Baseline variant

Use ref `origin/latest`. Allow only these files:

- `AGENTS.md`
- `docs/agents/media_type_integration.md`
- `README.md`

### Implemented variant

Use the current implemented branch at `HEAD`. Allow only these files:

- `AGENTS.md`
- `docs/agents/media_type_integration.md`
- `README.md`
- `docs/agents/domain_model.md`
- `src/api/contracts/openapi.yaml`
- `mcp_server/README.md`

Do not provide or permit any other file. In particular, do not provide raw source models, task modules, Celery settings, or other settings files. Do not follow imports, links, or file references into unlisted files. This restriction measures the shipped grounding artifacts, not the evaluator's ability to inspect implementation source.

## Exact system prompt

For each run, replace only `{{VARIANT_NAME}}`, `{{REF}}`, and `{{ALLOWED_FILES}}`. Preserve all other text exactly. Set `{{ALLOWED_FILES}}` to the matching list above.

```text
You are evaluating repository grounding for Floppy.

Variant: {{VARIANT_NAME}}
Repository ref: {{REF}}
Allowed files:
{{ALLOWED_FILES}}

Use only the allowed files for this named variant. Do not use outside knowledge, unstated assumptions, inference, other repository files, or answers from another run.

Answer each question separately. Cite every factual statement in the exact form ref:path:line. Use the repository ref named above as ref. A citation must point to an allowed file and to line content that directly supports the statement.

If the allowed context does not support an answer, write exactly: Unknown from the allowed context.

Use concise, literal language.

Questions:
1. What does `media_type_config` refer to in Floppy, and which source owns canonical media-type values?
2. What is the difference between an Item and a Consumption?
3. Which Celery queue and priority does the Reload calendar task use?
```

Do not add a separate user prompt that contains facts, hints, or prior answers. The runner may supply the allowed file contents through its normal repository tools.

## Citation rules

Use citations in the exact form `ref:path:line`, for example `HEAD:docs/agents/domain_model.md:7`. Use one citation for each factual statement. Use more than one citation when no single allowed line supports the complete statement.

A citation is invalid when any of these conditions applies:

- The ref is not the ref assigned to that variant.
- The path is not allowed for that variant.
- The path or line does not exist at the evaluated SHA.
- The cited line does not directly support the factual statement.
- The citation relies on a linked, imported, generated, or raw source file outside the allowed list.
- The answer gives a bare path, a line range, or a citation in another format.

Treat an answer that uses any disallowed evidence as a score of `0` for that question. Do not repair citations during scoring.

## Scoring rubric

Score each answer independently on this exact scale:

- `2`: All required facts are correct. Each factual statement has a valid allowed citation. The answer makes no unsupported claim.
- `1`: The answer is directionally correct but incomplete or ambiguous, or one material claim lacks a valid citation. The answer contains no contradiction.
- `0`: The answer is wrong or contradictory, cannot answer, uses disallowed evidence, or lacks citations.

The required facts are:

### Question 1

- There is no module named `media_type_config`.
- The actual runtime registry is `app.config.MEDIA_TYPE_CONFIG`.
- `app.models.choices.MediaTypes` owns the canonical media-type values.

### Question 2

- An Item is the shared provider identity or work.
- A Consumption is a per-user tracking record.
- A Consumption holds status, progress, score, dates, and notes.
- Multiple users or multiple Consumption records can relate to the same Item.

### Question 3

- The queue is `celery`.
- The priority is `9`, which is background priority.
- The Reload calendar task has no queue override, so the default queue applies.

Do not award correctness for facts that lack valid citations. Do not penalize an evaluator for saying `Unknown from the allowed context.` beyond the score of `0` defined above.

## Execution protocol

1. Resolve and record the baseline and implemented SHAs.
2. Start three fresh, clean-context evaluators. Give each evaluator a unique ID.
3. Have each evaluator answer all three questions for the baseline variant and all three questions for the implemented variant.
4. Start each variant run without prior answers or messages. Do not share answers between evaluators or variants.
5. Retain every raw answer exactly as returned.
6. Have a scorer independently check each answer against the rubric and the file contents at the recorded SHA. Do not let an evaluator score its own answer.
7. Record one score per evaluator, variant, and question.
8. Calculate the median of the three scores for each question in each variant.
9. Compare question medians. No question may regress: each implemented median must be greater than or equal to its baseline median.
10. Permit a conditional workstream only when its target-question median improves by at least `1` point, no other question regresses, and the proposed artifact has a named access path.

Do not combine the three questions into one answer or one score. Do not average scores across questions.

## Raw result template

Add one row for every evaluator, variant, and question. Preserve the raw answer verbatim.

| Evaluator ID | Variant | Ref | SHA | Question | Raw answer | Citations | Score (`0`-`2`) | Scorer notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `<evaluator ID>` | `<baseline or implemented>` | `<ref>` | `<SHA>` | `<1, 2, or 3>` | `<verbatim answer>` | `<citations as returned>` | `<score>` | `<citation and fact check>` |

## Median result template

| Question | Baseline median | Implemented median | Change | Regressed? | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | `<median>` | `<median>` | `<implemented minus baseline>` | `<yes or no>` | `<notes>` |
| 2 | `<median>` | `<median>` | `<implemented minus baseline>` | `<yes or no>` | `<notes>` |
| 3 | `<median>` | `<median>` | `<implemented minus baseline>` | `<yes or no>` | `<notes>` |

## Conditional workstream decisions

`W2` is the JSON-LD workstream. Proceed only if a named optional MCP resource improves a domain question without adding a runtime dependency. The record must name the resource and its repository or MCP access path. Otherwise, defer `W2`.

`W3` is the AsyncAPI workstream. Proceed only if verified event or channel evidence improves the queue or event question beyond the vocabulary guide and OpenAPI artifact. The record must name the artifact and its repository or MCP access path. Otherwise, defer `W3`.

Apply the same numeric gate to either workstream: the target-question median must improve by at least `1` point, and no other question may regress.

| Workstream | Target question | Proposed artifact or resource | Named access path | Comparison ref and SHA | Baseline median | Candidate median | Change | Other regression? | Decision (`proceed` or `defer`) | Evidence and reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W2 JSON-LD | `<1 or 2>` | `<named optional MCP resource>` | `<resource URI or repository path>` | `<ref and SHA>` | `<median>` | `<median>` | `<candidate minus baseline>` | `<yes or no>` | `<proceed or defer>` | `<evidence-based reason>` |
| W3 AsyncAPI | `3` | `<named event or channel artifact>` | `<resource URI or repository path>` | `<ref and SHA>` | `<median>` | `<median>` | `<candidate minus baseline>` | `<yes or no>` | `<proceed or defer>` | `<evidence-based reason>` |

Do not treat vocabulary or OpenAPI repetition as evidence for `W3`. Do not approve either workstream from an aggregate score when its target question does not meet the gate.

## Limitations

- Model behavior can drift between runs.
- The runner does not expose or control temperature.
- Three runs provide a small qualitative sample, not statistical confidence.
- The questions and evidence are repository-specific.
- The evaluation is not production telemetry or runtime analytics.

Leave all result fields blank until evaluators complete the protocol. Do not invent answers, citations, scores, SHAs, access paths, or decisions.
