## Summary
- Describe what changed and why.

## AI Assistance
- If an AI agent generated or substantially shaped this change, name the specific model (e.g. `claude-sonnet-4-6`, `gpt-5.1-codex`). A tool or subscription name alone ("Claude Code", "Copilot", "Codex Subscription") is NOT sufficient — say which model actually did the work. Delete this section only if no AI assistance was used.

## Validation
- List commands run and outcomes.

## Migration Sync Gate (Required for `upstream` -> `latest` sync PRs)
- [ ] Conflicts resolved with upstream files preserved and fork behavior merged intentionally.
- [ ] Migration conflicts handled per policy (no rewrite of shared/released migrations).
- [ ] `cd src && python manage.py makemigrations --merge` run for affected apps.
- [ ] `cd src && python manage.py check_migration_hygiene --strict` passed.
- [ ] `scripts/replay_upgrade_matrix.sh --from-tag <previous_release_tag> --to-ref latest --db sqlite,postgres --with-drift-scenarios` passed.
- [ ] `coverage run src/manage.py test app users integrations lists events --parallel` passed.

## Notes
- Link relevant issues (for example: `Refs #101`).
