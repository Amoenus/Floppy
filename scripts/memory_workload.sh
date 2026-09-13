#!/usr/bin/env bash
# Invoked by benchmark_memory.sh --workload-script scripts/memory_workload.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${FLOPPY_BENCHMARK_PROJECT:?Use the disposable benchmark harness}"
case "$FLOPPY_BENCHMARK_PROJECT" in
  floppy-memory-*) ;;
  *) echo "Refusing a non-benchmark compose project" >&2; exit 2 ;;
esac
compose=(docker compose -p "$FLOPPY_BENCHMARK_PROJECT" -f docker-compose.memory-benchmark.yml)
"${compose[@]}" cp scripts/memory_workload.py floppy:/tmp/floppy-memory-workload.py
"${compose[@]}" exec -T --user abc \
  -e FLOPPY_MEMORY_FIXTURE=disposable \
  -e FLOPPY_MEMORY_SCALES="${FLOPPY_MEMORY_SCALES:-500,2000}" \
  floppy python /tmp/floppy-memory-workload.py
