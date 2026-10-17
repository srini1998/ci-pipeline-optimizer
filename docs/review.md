# Engineering review / October 17, 2026

## problem
Explain CI duration with dependencies and observed timings; do not equate mixed outcomes with proven flakiness.

## example
Compare supported test/build chains. Reject cycles and missing dependencies explicitly.

## dataSource
Authored workflow/run-history fixtures; optional read-only GitHub ingestion.

## verification
43 passing checks include invalid graphs and GitHub response adapters.

## limitations
Average-duration critical path and mixed-outcome heuristic; no guaranteed savings or proof of nondeterministic failures.

## Reproduce
Python 3.12, free project requirements and pytest: `python -m pytest tests -q`. Actual output: docs/test-results.txt. No paid API calls used. Optional local generation needs Ollama/qwen2.5:3b.
