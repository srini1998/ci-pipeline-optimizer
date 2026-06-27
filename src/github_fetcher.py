"""
GitHub API Fetcher
------------------
Pulls live workflow YAML and run history directly from the GitHub API.
Uses only stdlib (urllib) — no extra dependencies.

Usage:
    fetcher = GitHubFetcher("myorg/myapp", token="ghp_...", workflow_name="CI Pipeline")
    history, yaml_text = fetcher.fetch_all(max_runs=30)
"""

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


API_BASE = "https://api.github.com"


class GitHubFetcher:
    def __init__(
        self,
        repo: str,
        token: Optional[str] = None,
        workflow_name: Optional[str] = None,
    ):
        """
        repo          — "owner/repo" (e.g. "myorg/myapp")
        token         — GitHub PAT or GITHUB_TOKEN env var. Public repos work without one,
                        but rate limit drops to 60 req/hr unauthenticated.
        workflow_name — workflow display name or filename (e.g. "CI Pipeline" or "ci.yml").
                        When omitted, the first workflow found is used.
        """
        self.repo = repo
        self.token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        self.workflow_name = workflow_name

    # ── Public API ────────────────────────────────────────────────────────────

    def fetch_all(self, max_runs: int = 30) -> Tuple[dict, str]:
        """
        Return (history_dict, workflow_yaml_string).
        history_dict matches the local run_history.json schema.
        """
        workflow_id, workflow_path = self._resolve_workflow()
        yaml_text = self._fetch_workflow_yaml(workflow_path)
        history = self._fetch_run_history(workflow_id, max_runs)
        return history, yaml_text

    def fetch_run_history(self, max_runs: int = 30) -> dict:
        """Return only the run history dict (when you already have a local workflow YAML)."""
        workflow_id, _ = self._resolve_workflow()
        return self._fetch_run_history(workflow_id, max_runs)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _resolve_workflow(self) -> Tuple[str, str]:
        """Returns (workflow_id, workflow_path) for the target workflow."""
        url = f"{API_BASE}/repos/{self.repo}/actions/workflows"
        data = self._get(url)
        workflows = data.get("workflows", [])

        if not workflows:
            raise ValueError(f"No workflows found in {self.repo}")

        if self.workflow_name:
            for wf in workflows:
                name_match = wf["name"] == self.workflow_name
                path_match = (
                    self.workflow_name in wf["path"]
                    or os.path.basename(wf["path"]) == self.workflow_name
                )
                if name_match or path_match:
                    return str(wf["id"]), wf["path"]
            available = [w["name"] for w in workflows]
            raise ValueError(
                f"Workflow '{self.workflow_name}' not found. "
                f"Available: {available}"
            )

        wf = workflows[0]
        return str(wf["id"]), wf["path"]

    def _fetch_workflow_yaml(self, path: str) -> str:
        """Download and decode the raw YAML of a workflow file."""
        url = f"{API_BASE}/repos/{self.repo}/contents/{path}"
        data = self._get(url)
        encoded = data.get("content", "").replace("\n", "")
        return base64.b64decode(encoded).decode("utf-8")

    def _fetch_run_history(self, workflow_id: str, max_runs: int) -> dict:
        """Fetch up to max_runs completed runs and convert to our history schema."""
        per_page = min(max_runs, 100)
        url = (
            f"{API_BASE}/repos/{self.repo}/actions/workflows/{workflow_id}/runs"
            f"?per_page={per_page}&status=completed"
        )
        data = self._get(url)
        raw_runs = data.get("workflow_runs", [])[:max_runs]

        runs = []
        for run in raw_runs:
            jobs = self._fetch_jobs(run["id"])
            runs.append({
                "run_id": str(run["id"]),
                "timestamp": run.get("run_started_at") or run.get("created_at", ""),
                "trigger": run.get("event", "push"),
                "branch": run.get("head_branch", ""),
                "status": "success" if run.get("conclusion") == "success" else "failure",
                "jobs": {job["name"]: self._convert_job(job) for job in jobs},
            })

        workflow_name = raw_runs[0]["name"] if raw_runs else "Unknown"
        return {
            "workflow_name": workflow_name,
            "repo": self.repo,
            "runs": runs,
        }

    def _fetch_jobs(self, run_id: int) -> List[dict]:
        url = f"{API_BASE}/repos/{self.repo}/actions/runs/{run_id}/jobs?per_page=100"
        return self._get(url).get("jobs", [])

    @staticmethod
    def _convert_job(job: dict) -> dict:
        duration = 0
        if job.get("started_at") and job.get("completed_at"):
            fmt = "%Y-%m-%dT%H:%M:%SZ"
            try:
                start = datetime.strptime(job["started_at"], fmt).replace(tzinfo=timezone.utc)
                end = datetime.strptime(job["completed_at"], fmt).replace(tzinfo=timezone.utc)
                duration = max(0, int((end - start).total_seconds()))
            except ValueError:
                pass

        conclusion = job.get("conclusion") or "unknown"
        status = {"success": "success", "failure": "failure", "skipped": "skipped"}.get(
            conclusion, "unknown"
        )
        runner = (job.get("labels") or ["ubuntu-latest"])[0]
        return {"duration_seconds": duration, "status": status, "runner": runner}

    def _get(self, url: str) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ci-pipeline-optimizer/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            if exc.code == 401:
                raise RuntimeError("GitHub API: unauthorized. Set GITHUB_TOKEN or pass --token.")
            if exc.code == 403:
                raise RuntimeError(
                    "GitHub API: forbidden. Rate limit hit or insufficient permissions.\n"
                    "Tip: authenticate with --token to raise limit to 5000 req/hr."
                )
            if exc.code == 404:
                raise RuntimeError(f"GitHub API: repo or workflow not found — {self.repo}")
            raise RuntimeError(f"GitHub API error {exc.code}: {body}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error reaching GitHub API: {exc.reason}")
