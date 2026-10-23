# Public run recordings

Captured by `scripts/snapshot.mjs` through the unauthenticated GitHub REST API. Each entry in `src/snapshots.json` retains the repository, workflow/run ID, commit SHA, capture timestamp, run timestamp, original public job/run URLs, step timings and workflow YAML fetched at the run's exact SHA. No logs, artifacts or credentials are fetched.

Sources: sindresorhus/p-limit (MIT), pallets/click (BSD-3-Clause), expressjs/express (MIT). Public timing metadata and short workflow definitions are used for analysis; no affiliation is implied. Full upstream license notices are included in `LICENSES/`. Recordings are historical, clearly labeled cached, and can be reproduced with the refresh script. A sample of one run per repository cannot establish representative duration or flakiness.
