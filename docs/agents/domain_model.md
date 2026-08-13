<!-- GENERATED FILE. DO NOT EDIT. Run `PYTHONPATH=src uv run --no-sync python -m app.domain_vocabulary` to regenerate. -->

# Floppy domain model

Use these terms when you change Floppy or its API.

## Item

An Item is the shared work that Floppy identifies from a media provider. Users can track the same Item with separate Consumption records.

Bounded context: `app`.

Aliases: `work`.

Relationships:
- Has user tracking record: [Consumption](#consumption).
- Is classified by: [Media type](#media-type).

Schema.org type: `https://schema.org/CreativeWork`.

## Consumption

A Consumption is one user's tracking record for an Item. It stores the user's status, progress, score, dates, and notes.

Bounded context: `app`.

Aliases: `tracking record`, `media entry`.

Relationships:
- Tracks: [Item](#item).

## Media type

A Media type classifies an Item. Canonical values come from `app.models.choices.MediaTypes`. API season and episode routes are nested under `tv`; season and episode are not top-level media types.

Bounded context: `app`.

Aliases: `media kind`.

Relationships:
- Classifies: [Item](#item).

## Celery queue

A Celery queue sends a task to a worker. Floppy uses the `celery`, `interactive`, and `discover` queue names. `celery` handles background work. `interactive` handles user-triggered work. `discover` handles Discover cache rebuilds. The Reload calendar task has no queue override, so Celery routes it to `celery` at background priority.

Bounded context: `config`.

Aliases: `task queue`.

Relationships:
- Processes calendar updates for: [Item](#item).
