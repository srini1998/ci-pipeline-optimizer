#!/usr/bin/env python3
"""
CI Pipeline Optimizer — CLI
----------------------------
Two data source modes:

  Local files (existing):
    python main.py --workflow sample_data/workflow.yml --history sample_data/run_history.json

  GitHub API (live data):
    python main.py --repo myorg/myapp [--workflow-name "CI Pipeline"] [--token ghp_xxx]

Outputs:
  - Colour terminal report (default)
  - JSON report file (--json-output)
"""

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from analyzer import WorkflowAnalyzer
from reporter import generate_terminal_report, generate_json_report


def parse_args():
    parser = argparse.ArgumentParser(
        description="CI Pipeline Optimizer — find bottlenecks, flaky tests, and parallelization wins.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local files
  python main.py --workflow .github/workflows/ci.yml --history run_history.json

  # Live GitHub data (no local files needed)
  python main.py --repo myorg/myapp --token ghp_xxx

  # Specific workflow + save report
  python main.py --repo myorg/myapp --workflow-name "CI Pipeline" --json-output report.json
""",
    )

    # ── Data source: local files ──────────────────────────────────────────────
    local = parser.add_argument_group("local file mode")
    local.add_argument("--workflow", help="Path to GitHub Actions workflow YAML file")
    local.add_argument("--history", help="Path to run history JSON file")

    # ── Data source: GitHub API ───────────────────────────────────────────────
    gh = parser.add_argument_group("github api mode")
    gh.add_argument("--repo", metavar="OWNER/REPO",
                    help="Fetch live data from GitHub (e.g. myorg/myapp)")
    gh.add_argument("--workflow-name", metavar="NAME",
                    help="Workflow name or filename to analyse (default: first workflow found)")
    gh.add_argument("--token", metavar="TOKEN",
                    help="GitHub PAT. Falls back to GITHUB_TOKEN / GH_TOKEN env vars.")
    gh.add_argument("--max-runs", type=int, default=30,
                    help="Number of recent runs to fetch from GitHub (default: 30)")

    # ── Output options ────────────────────────────────────────────────────────
    parser.add_argument("--json-output", default=None,
                        help="Write machine-readable JSON report to this file")
    parser.add_argument("--flaky-threshold", type=float, default=0.2,
                        help="Flakiness score threshold (0.0–1.0). Default: 0.2")
    parser.add_argument("--slow-threshold", type=float, default=300,
                        help="Duration threshold in seconds to flag as slow. Default: 300")

    return parser.parse_args()


def main():
    args = parse_args()

    if args.repo:
        # ── GitHub API mode ───────────────────────────────────────────────────
        from github_fetcher import GitHubFetcher
        print(f"  Fetching data from GitHub: {args.repo} …", file=sys.stderr)
        fetcher = GitHubFetcher(args.repo, args.token, args.workflow_name)
        try:
            history_data, workflow_yaml = fetcher.fetch_all(max_runs=args.max_runs)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        print(
            f"  Fetched {len(history_data['runs'])} runs for "
            f"'{history_data['workflow_name']}'",
            file=sys.stderr,
        )

        # Write to temp files so WorkflowAnalyzer can load them
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as wf:
            wf.write(workflow_yaml)
            workflow_path = wf.name

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as hf:
            json.dump(history_data, hf)
            history_path = hf.name

        cleanup = [workflow_path, history_path]

    else:
        # ── Local file mode ───────────────────────────────────────────────────
        if not args.workflow or not args.history:
            print(
                "Error: provide either --repo (GitHub API) "
                "or both --workflow and --history (local files).",
                file=sys.stderr,
            )
            sys.exit(1)

        if not os.path.exists(args.workflow):
            print(f"Error: workflow file not found: {args.workflow}", file=sys.stderr)
            sys.exit(1)
        if not os.path.exists(args.history):
            print(f"Error: history file not found: {args.history}", file=sys.stderr)
            sys.exit(1)

        workflow_path = args.workflow
        history_path = args.history
        cleanup = []

    try:
        analyzer = WorkflowAnalyzer(workflow_path, history_path)
        analyzer.load()

        print(generate_terminal_report(analyzer))

        if args.json_output:
            out_dir = os.path.dirname(os.path.abspath(args.json_output))
            os.makedirs(out_dir, exist_ok=True)
            with open(args.json_output, "w") as f:
                json.dump(generate_json_report(analyzer), f, indent=2)
            print(f"\n  JSON report saved to: {args.json_output}")

    finally:
        for path in cleanup:
            try:
                os.unlink(path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
