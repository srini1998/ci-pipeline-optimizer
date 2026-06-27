"""
CI Pipeline Analyzer
--------------------
Parses GitHub Actions workflow YAML and run history JSON.
Produces timing stats, flakiness scores, and dependency graphs.
"""

import json
import yaml
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class JobStats:
    name: str
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    durations: List[float] = field(default_factory=list)

    @property
    def avg_duration(self) -> float:
        active = [d for d in self.durations if d > 0]
        return statistics.mean(active) if active else 0.0

    @property
    def max_duration(self) -> float:
        active = [d for d in self.durations if d > 0]
        return max(active) if active else 0.0

    @property
    def min_duration(self) -> float:
        active = [d for d in self.durations if d > 0]
        return min(active) if active else 0.0

    @property
    def failure_rate(self) -> float:
        if self.run_count == 0:
            return 0.0
        return self.failure_count / self.run_count

    @property
    def flakiness_score(self) -> float:
        """
        Flakiness = failure_rate weighted by how often it flips.
        A job that always fails is a broken job, not flaky.
        A job that fails ~30-70% of the time is flaky.
        Score: 0.0 (stable) to 1.0 (maximally flaky)
        """
        if self.run_count < 2:
            return 0.0
        rate = self.failure_rate
        # Bell curve centered at 0.5 - jobs that fail ~half the time are flakiest
        flakiness = 1.0 - abs(rate - 0.5) * 2
        return round(max(0.0, flakiness), 3)

    @property
    def duration_variance(self) -> float:
        active = [d for d in self.durations if d > 0]
        if len(active) < 2:
            return 0.0
        return round(statistics.stdev(active), 1)


@dataclass
class WorkflowJob:
    name: str
    needs: List[str] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    raw_steps: List[dict] = field(default_factory=list)
    runs_on: str = "ubuntu-latest"


_INSTALL_COMMANDS: Dict[str, List[str]] = {
    "pip":      ["pip install", "pip3 install"],
    "npm":      ["npm install", "npm ci"],
    "yarn":     ["yarn install", "yarn "],
    "poetry":   ["poetry install"],
    "composer": ["composer install"],
    "bundler":  ["bundle install"],
    "cargo":    ["cargo fetch"],
    "go":       ["go mod download"],
}

_TEST_COMMANDS = ["pytest", "jest ", "mocha ", "rspec", "go test", "cargo test", "npm test"]


def _cache_suggestion(managers: set) -> str:
    parts = []
    if "pip" in managers or "poetry" in managers:
        parts.append("actions/setup-python with cache: 'pip'")
    if "npm" in managers:
        parts.append("actions/setup-node with cache: 'npm'")
    if "yarn" in managers:
        parts.append("actions/setup-node with cache: 'yarn'")
    if not parts:
        parts.append("actions/cache with an appropriate restore-key")
    return "; ".join(parts)


class WorkflowAnalyzer:
    def __init__(self, workflow_path: str, history_path: str):
        self.workflow_path = workflow_path
        self.history_path = history_path
        self.workflow: Dict = {}
        self.history: Dict = {}
        self.jobs: Dict[str, WorkflowJob] = {}
        self.stats: Dict[str, JobStats] = {}

    def load(self):
        """Load both the workflow YAML and run history JSON."""
        with open(self.workflow_path) as f:
            self.workflow = yaml.safe_load(f)

        with open(self.history_path) as f:
            self.history = json.load(f)

        self._parse_workflow()
        self._compute_stats()

    def _parse_workflow(self):
        """Extract job definitions, dependencies, and steps from YAML."""
        raw_jobs = self.workflow.get("jobs", {})
        for job_name, job_def in raw_jobs.items():
            needs = job_def.get("needs", [])
            if isinstance(needs, str):
                needs = [needs]
            raw_steps_list = job_def.get("steps", [])
            steps = [
                step.get("name", step.get("uses", "unnamed"))
                for step in raw_steps_list
            ]
            self.jobs[job_name] = WorkflowJob(
                name=job_name,
                needs=needs,
                steps=steps,
                raw_steps=raw_steps_list,
                runs_on=job_def.get("runs-on", "ubuntu-latest"),
            )

    def _compute_stats(self):
        """Aggregate timing and status data across all runs."""
        for run in self.history.get("runs", []):
            for job_name, job_data in run.get("jobs", {}).items():
                if job_name not in self.stats:
                    self.stats[job_name] = JobStats(name=job_name)

                stat = self.stats[job_name]
                status = job_data.get("status", "unknown")

                if status == "skipped":
                    continue

                stat.run_count += 1
                stat.durations.append(job_data.get("duration_seconds", 0))

                if status == "success":
                    stat.success_count += 1
                elif status == "failure":
                    stat.failure_count += 1

    def get_critical_path(self) -> List[str]:
        """
        Find the longest dependency chain (critical path).
        This is the minimum possible total CI time.
        Uses topological sort + dynamic programming.
        """
        # Build adjacency: job -> list of jobs that depend on it
        dependents: Dict[str, List[str]] = {j: [] for j in self.jobs}
        for job_name, job in self.jobs.items():
            for dep in job.needs:
                if dep in dependents:
                    dependents[dep].append(job_name)

        # DP: longest path ending at each node
        memo: Dict[str, float] = {}

        def longest_path(job: str) -> float:
            if job in memo:
                return memo[job]
            duration = self.stats.get(job, JobStats(job)).avg_duration
            if not self.jobs[job].needs:
                memo[job] = duration
                return duration
            parent_max = max(longest_path(p) for p in self.jobs[job].needs)
            memo[job] = duration + parent_max
            return memo[job]

        for job in self.jobs:
            longest_path(job)

        # Trace back the critical path
        all_durations = {j: memo.get(j, 0) for j in self.jobs}
        critical_end = max(all_durations, key=all_durations.get)

        path = [critical_end]
        current = critical_end
        while self.jobs[current].needs:
            parent = max(
                self.jobs[current].needs,
                key=lambda p: memo.get(p, 0)
            )
            path.append(parent)
            current = parent

        return list(reversed(path))

    def get_parallelizable_groups(self) -> List[List[str]]:
        """
        Group jobs that could run in parallel (share the same dependencies).
        """
        groups: Dict[str, List[str]] = {}
        for job_name, job in self.jobs.items():
            key = tuple(sorted(job.needs))
            groups.setdefault(str(key), []).append(job_name)

        return [group for group in groups.values() if len(group) > 1]

    def get_flaky_jobs(self, threshold: float = 0.2) -> List[JobStats]:
        """Return jobs with flakiness score above the threshold."""
        return sorted(
            [s for s in self.stats.values() if s.flakiness_score > threshold],
            key=lambda s: s.flakiness_score,
            reverse=True,
        )

    def get_slow_jobs(self, threshold_seconds: float = 300) -> List[JobStats]:
        """Return jobs averaging over the threshold duration."""
        return sorted(
            [s for s in self.stats.values() if s.avg_duration > threshold_seconds],
            key=lambda s: s.avg_duration,
            reverse=True,
        )

    def get_total_sequential_time(self) -> float:
        """Total CI time if all jobs ran sequentially."""
        return sum(s.avg_duration for s in self.stats.values())

    def get_theoretical_parallel_time(self) -> float:
        """Minimum possible time if we maximize parallelism (critical path only)."""
        path = self.get_critical_path()
        return sum(self.stats.get(j, JobStats(j)).avg_duration for j in path)

    # ── New: timeline & recommendations ───────────────────────────────────────

    def _topological_order(self) -> List[str]:
        """Return jobs ordered so each dependency comes before its dependents."""
        visited: set = set()
        in_progress: set = set()
        order: List[str] = []

        def visit(job: str) -> None:
            if job in visited or job in in_progress:
                return
            in_progress.add(job)
            for dep in self.jobs[job].needs:
                if dep in self.jobs:
                    visit(dep)
            in_progress.discard(job)
            visited.add(job)
            order.append(job)

        for job in self.jobs:
            visit(job)
        return order

    def compute_timeline(self) -> Dict[str, Dict[str, float]]:
        """
        Compute optimal parallel start/end times assuming unlimited runners.
        Returns {job: {start, end, duration}} in seconds.
        """
        end_times: Dict[str, float] = {}
        result: Dict[str, Dict[str, float]] = {}

        for job in self._topological_order():
            duration = self.stats.get(job, JobStats(job)).avg_duration
            deps = [dep for dep in self.jobs[job].needs if dep in end_times]
            start = max((end_times[dep] for dep in deps), default=0.0)
            end = start + duration
            end_times[job] = end
            result[job] = {
                "start": round(start, 1),
                "end": round(end, 1),
                "duration": round(duration, 1),
            }

        return result

    @staticmethod
    def _step_uses_cache(steps: List[dict]) -> bool:
        for step in steps:
            uses = step.get("uses") or ""
            if "actions/cache" in uses:
                return True
            if "setup-python" in uses or "setup-node" in uses or "setup-java" in uses:
                if "cache" in (step.get("with") or {}):
                    return True
        return False

    def get_caching_recommendations(self) -> List[Dict]:
        """
        Find jobs that install packages without caching, grouped by package manager.
        """
        results = []
        for job_name, job in self.jobs.items():
            if self._step_uses_cache(job.raw_steps):
                continue
            detected: set = set()
            for step in job.raw_steps:
                run_cmd = step.get("run") or ""
                for manager, patterns in _INSTALL_COMMANDS.items():
                    if any(p in run_cmd for p in patterns):
                        detected.add(manager)
            if detected:
                stat = self.stats.get(job_name)
                results.append({
                    "job": job_name,
                    "package_managers": sorted(detected),
                    "avg_duration_seconds": round(stat.avg_duration, 1) if stat else 0.0,
                    "suggestion": _cache_suggestion(detected),
                })
        return results

    def get_sharding_recommendations(self, slow_threshold: float = 300) -> List[Dict]:
        """
        Recommend matrix sharding for slow jobs that run tests.
        """
        results = []
        for job_name, job in self.jobs.items():
            stat = self.stats.get(job_name)
            if not stat or stat.avg_duration <= slow_threshold:
                continue
            runs_tests = any(
                any(cmd in (step.get("run") or "") for cmd in _TEST_COMMANDS)
                for step in job.raw_steps
            )
            if not runs_tests:
                continue
            suggested = max(2, min(8, int(stat.avg_duration / 120)))
            results.append({
                "job": job_name,
                "avg_duration_seconds": round(stat.avg_duration, 1),
                "suggested_shards": suggested,
                "estimated_shard_duration_seconds": round(stat.avg_duration / suggested, 1),
            })
        return results
