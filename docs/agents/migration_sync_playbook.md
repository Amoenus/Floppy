# Migration Sync Playbook (`upstream` -> `latest`)

This playbook defines the required migration process for syncing upstream Yamtrack's `dev` branch into fork `latest` through the local `upstream` mirror.

## Branch model
- `upstream`: utility branch that must remain a byte-for-byte mirror of `upstream/dev` (the actual FuzzyGrim/Yamtrack `dev` branch). Never edit it directly or target it with a PR.
- `latest`: integration branch for fork features and upstream sync merges.
- `release`: versioned release/container publication flow.

Upstream changes are expected to require adaptation because `latest` contains fork-specific behavior. Treat the upstream commit as a source of intent, not as a commit to cherry-pick blindly; integrate it into `latest` and resolve differences deliberately.

## Migration policy
- Same migration numbers across branches are valid in Django.
- Resolve graph splits with merge migrations (`makemigrations --merge`), not wholesale rewrites.
- Keep upstream migration filenames unchanged in `latest`.
- Renumber only fork-local migrations that are unpushed and unreleased.
- Never rewrite migrations that already exist in `origin/latest` or any `v*` release tag.
- In fork-authored migrations, use idempotent wrappers for risky schema add/remove operations.

## Sync SOP (hard gate)
1. Update and verify mirror branch:
   - `git checkout upstream`
   - `git fetch upstream`
   - `git reset --hard upstream/dev`
2. Merge upstream mirror into integration branch:
   - `git checkout latest`
   - `git merge --no-ff upstream`
3. Resolve conflicts:
   - Keep upstream maintenance changes.
   - Keep fork-visible behavior and UX.
   - Adapt upstream changes to the fork instead of assuming a cherry-pick will apply cleanly or preserve the intended behavior.
   - For migration conflicts, follow policy above.
4. Resolve migration graph:
   - `cd src && python manage.py makemigrations --merge`
   - Repeat until affected apps have one leaf node.
5. Run migration hygiene command:
   - `cd src && python manage.py check_migration_hygiene --strict`
6. Run dual-DB upgrade replay:
   - `scripts/replay_upgrade_matrix.sh --from-tag <previous_release_tag> --to-ref latest --db sqlite,postgres --with-drift-scenarios`
7. Run standard tests:
   - `coverage run src/manage.py test app users integrations lists events --parallel`
8. Do not merge sync work until all gates pass.

## Required drift scenario coverage
- Drift scenarios are executed in Postgres replay.
- Baseline scenario for issue class `#101`:
  1. Migrate to `users.0067_remove_user_tv_sort_valid_and_more`.
  2. Drop `boardgame_sort_valid` manually.
  3. Apply `users.0068_remove_user_tv_sort_valid_and_more`.
  4. Confirm migration succeeds.

## Troubleshooting guidance
- If `check_migration_hygiene` reports multiple leaf nodes:
  - Run `makemigrations --merge` for the app it reports.
- If risky raw operations are flagged:
  - Replace raw `migrations.AddConstraint/RemoveConstraint` (and index equivalents) with idempotent wrappers in fork-authored migrations.
- If replay passes on SQLite but fails on Postgres:
  - Treat Postgres failure as blocking and patch migration idempotency before merge.
