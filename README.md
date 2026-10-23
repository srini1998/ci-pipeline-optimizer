# CI Pipeline Optimizer

Explain CI duration with dependencies and observed timings; do not equate mixed outcomes with proven flakiness.

Compare supported test/build chains. Reject cycles and missing dependencies explicitly.

See [review](docs/review.md) and [actual checks](docs/test-results.txt) for data, validation and limitations.

```sh
python -m pytest tests -q
```

No production-readiness or independent model-quality guarantee is claimed.

## Build Sheet: public CI timing workbench

`site/` is a browser successor to the Python analyzer. It parses real workflow YAML, maps job timings from three recorded public GitHub Actions runs, draws the dependency critical path, and models caching / balanced test sharding including repeated setup and shard overhead. Paste a public repository (four unauthenticated requests max) or YAML. YAML and scripts are never executed; nothing dispatches Actions or edits repositories.

Run `cd site && npm ci && npm test && npm run build`. `npm run snapshot` refreshes bounded, provenance-bearing public recordings. `npm run dev` opens port 5214. The original Python tests remain separate (`python -m pytest tests -q`).

Timings are one-run samples, not historical averages or proof of flakiness. Matrix groups use the slowest observed child and assume unlimited runners; conditional jobs, concurrency limits and reusable-workflow internals are not executed. Unmatched jobs default to clearly labeled editable 60-second estimates. Savings are simulated, not benchmarked improvements. Runner-time totals describe collapsed templates, not billing or complete matrix consumption. The interface uses no LLM or paid service. GitHub's unauthenticated quota applies to the visitor's IP; no paid fallback or credential input exists.
