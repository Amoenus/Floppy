#!/usr/bin/env bash
# Tiered test runner. Default is the fast suite (excludes @tag("slow")
# benchmark/Playwright tests) with bounded output via --buffer.
#
# Usage:
#   scripts/test.sh                       Fast suite (default; use this)
#   scripts/test.sh <label> [...]         Targeted run, e.g. app.tests.test_query_counts
#   scripts/test.sh --full                Full suite incl. slow tests (20+ min,
#                                         needs `playwright install`)
#   scripts/test.sh --slow                Only @tag("slow") tests
#
# Extra manage.py test flags (e.g. -v 2, --failfast) pass through after the mode.
set -euo pipefail

cd "$(dirname "$0")/.."

APPS=(app users integrations lists events)
COMMON=(--parallel --buffer)

case "${1:-}" in
  --full)
    shift
    exec python src/manage.py test "${APPS[@]}" "${COMMON[@]}" "$@"
    ;;
  --slow)
    shift
    exec python src/manage.py test "${APPS[@]}" "${COMMON[@]}" --tag slow "$@"
    ;;
  "")
    exec python src/manage.py test "${APPS[@]}" "${COMMON[@]}" --exclude-tag slow
    ;;
  *)
    exec python src/manage.py test "${COMMON[@]}" "$@"
    ;;
esac
