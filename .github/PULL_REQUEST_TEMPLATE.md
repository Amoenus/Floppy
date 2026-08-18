## Summary
- What changed and why in plain, approachable terms.
- For user interface or visual changes, attach before and after screenshots.

## AI Assistance
- If an AI assistant (such as Claude, Codex, Copilot) generated or shaped this code, specify the exact model name (e.g. `claude-sonnet-4-6`, `gpt-4o`).
- If no AI assistance was used, delete this section.

## How It Was Tested
- List the test commands you ran and their outcomes (e.g. `scripts/test.sh users.tests.views.test_about` -> Passed).

## Public API & Documentation Handoff
- [ ] Domain terminology is up to date (`python -m app.domain_vocabulary --check`)
- [ ] OpenAPI schema contracts verified (if API endpoints changed)
- [ ] Not applicable (no API or vocabulary changes)

## Human Review & Quality Assurance
- [ ] Code review completed
- [ ] Visual or manual QA verified (e.g. `/gstack-qa` or browser testing)

## Database & Migration Safety (Only if modifying models)
- [ ] No existing or shared migrations were altered or renumbered
- [ ] Migration hygiene passed (`uv run --no-sync python src/manage.py check_migration_hygiene --strict`)
- [ ] Not applicable (no database changes)

## Related Issues
- Link relevant issues and PRs (e.g. `Fixes #123`, `Refs #456`).

