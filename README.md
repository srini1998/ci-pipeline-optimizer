# CI Pipeline Optimizer

> **"Code validation is the next big bottleneck."** — Blacksmith NYC Meetup, June 2026

As AI coding tools generate code faster than ever, the bottleneck shifts to **validating** that code — running builds, tests, and checks. This tool helps engineering teams identify and eliminate CI inefficiencies before they become the ceiling on developer velocity.

---

## What It Does

Analyzes your GitHub Actions workflow and run history to surface:

| Feature | What it finds |
|---|---|
| **Slow jobs** | Jobs averaging over a configurable threshold |
| **Flaky tests** | Jobs with unpredictable pass/fail patterns |
| **Critical path** | The longest dependency chain — your true CI bottleneck |
| **Parallelization wins** | Jobs that share dependencies and can run concurrently |
| **Duration variance** | Jobs with inconsistent runtimes (sign of cold runners or network I/O) |

---

## Quick Start

```bash
# Install dependencies
pip install pyyaml pytest

# Run the analyzer
python src/main.py \
  --workflow sample_data/workflow.yml \
  --history  sample_data/run_history.json \
  --json-output reports/report.json
```

### Example Output

```
📊 PIPELINE SUMMARY
  Total runs analyzed : 10
  Sequential time     : 16m 50s
  Optimal parallel    : 13m 40s
  Potential savings   : 3m 09s (19%)

🔗 CRITICAL PATH
  lint → integration-tests → build-docker → deploy-staging

🎲 FLAKY JOB DETECTION
  integration-tests    flakiness: 0.667   failure rate: 33.3%

⚡ PARALLELIZATION OPPORTUNITIES
  unit-tests + integration-tests can run in parallel → saves 3m 09s/run

💡 RECOMMENDATIONS
  1. [SLOW]    'integration-tests' averages 7m 19s — consider sharding.
  2. [FLAKY]   'integration-tests' score 0.67 — investigate race conditions.
  3. [PARALLEL] unit-tests, integration-tests share dependencies — parallelize.
```

---

## Core Concepts

### 1. Flakiness Score
A flaky test is one that randomly passes and fails without code changes. The score is highest (~1.0) for jobs that fail ~50% of the time, and lowest (0.0) for jobs that always pass or always fail.

```
flakiness = 1 - |failure_rate - 0.5| * 2
```

A job that always fails is **broken**, not flaky. A job that fails half the time is **maximally flaky**.

### 2. Critical Path Analysis
Uses topological sort + dynamic programming to find the longest dependency chain. This is the minimum achievable CI time even with infinite parallelism — your true bottleneck.

### 3. Parallelization Detection
Jobs that share the same set of dependencies can be run concurrently. The tool groups these and calculates per-run time savings.

---

## Project Structure

```
ci_optimizer/
├── src/
│   ├── analyzer.py     # Core logic: parse YAML, compute stats, find bottlenecks
│   ├── reporter.py     # Terminal + JSON report generation
│   └── main.py         # CLI entry point
├── tests/
│   └── test_analyzer.py  # 19 unit tests (all passing)
├── sample_data/
│   ├── workflow.yml      # Sample GitHub Actions workflow
│   └── run_history.json  # Sample run history (10 runs)
└── reports/              # Generated reports land here
```

---

## Running Tests

```bash
python -m pytest tests/ -v
# 19 passed in 0.09s
```

---

## Why This Matters

In the era of AI-assisted development:
- AI agents write code **100x faster** than humans
- But CI still takes the same 10–30 minutes it always has
- Every slow, flaky, or unparallelized job compounds this bottleneck

This tool helps teams **measure first, optimize second** — the right engineering approach.

---

## Input Format

### Workflow YAML
Standard GitHub Actions `.github/workflows/*.yml` format.

### Run History JSON
```json
{
  "workflow_name": "CI Pipeline",
  "repo": "myorg/myapp",
  "runs": [
    {
      "run_id": "run_001",
      "timestamp": "2026-06-20T09:00:00Z",
      "status": "success",
      "jobs": {
        "lint": {"duration_seconds": 45, "status": "success", "runner": "ubuntu-latest"},
        "test": {"duration_seconds": 180, "status": "success", "runner": "ubuntu-latest"}
      }
    }
  ]
}
```

Can be generated from the GitHub Actions API:
```bash
gh api repos/{owner}/{repo}/actions/runs --paginate > run_history.json
```
