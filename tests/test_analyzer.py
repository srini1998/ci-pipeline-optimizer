"""
Tests for CI Pipeline Analyzer
"""
import json
import os
import sys
import tempfile
import base64
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from analyzer import WorkflowAnalyzer, JobStats
from github_fetcher import GitHubFetcher


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_WORKFLOW = """
name: Test CI
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: Lint code
        run: echo lint
  test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - name: Run tests
        run: echo tests
  deploy:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - name: Deploy
        run: echo deploy
"""

SAMPLE_HISTORY = {
    "workflow_name": "Test CI",
    "repo": "test/repo",
    "runs": [
        {
            "run_id": "r1", "timestamp": "2026-06-01T09:00:00Z",
            "trigger": "push", "branch": "main", "status": "success",
            "jobs": {
                "lint": {"duration_seconds": 30, "status": "success", "runner": "ubuntu-latest"},
                "test": {"duration_seconds": 120, "status": "success", "runner": "ubuntu-latest"},
                "deploy": {"duration_seconds": 60, "status": "success", "runner": "ubuntu-latest"},
            }
        },
        {
            "run_id": "r2", "timestamp": "2026-06-01T11:00:00Z",
            "trigger": "push", "branch": "main", "status": "failure",
            "jobs": {
                "lint": {"duration_seconds": 28, "status": "success", "runner": "ubuntu-latest"},
                "test": {"duration_seconds": 110, "status": "failure", "runner": "ubuntu-latest"},
                "deploy": {"duration_seconds": 0, "status": "skipped", "runner": "ubuntu-latest"},
            }
        },
        {
            "run_id": "r3", "timestamp": "2026-06-01T13:00:00Z",
            "trigger": "push", "branch": "main", "status": "success",
            "jobs": {
                "lint": {"duration_seconds": 32, "status": "success", "runner": "ubuntu-latest"},
                "test": {"duration_seconds": 130, "status": "success", "runner": "ubuntu-latest"},
                "deploy": {"duration_seconds": 65, "status": "success", "runner": "ubuntu-latest"},
            }
        },
    ]
}


@pytest.fixture
def analyzer(tmp_path):
    workflow_file = tmp_path / "workflow.yml"
    history_file = tmp_path / "history.json"

    workflow_file.write_text(SAMPLE_WORKFLOW)
    history_file.write_text(json.dumps(SAMPLE_HISTORY))

    a = WorkflowAnalyzer(str(workflow_file), str(history_file))
    a.load()
    return a


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestJobStats:
    def test_avg_duration_ignores_zeros(self):
        s = JobStats(name="test", durations=[100, 200, 0, 150])
        assert s.avg_duration == pytest.approx(150.0)

    def test_failure_rate(self):
        s = JobStats(name="test", run_count=4, failure_count=1)
        assert s.failure_rate == pytest.approx(0.25)

    def test_flakiness_score_max_at_50_percent(self):
        # A job failing exactly 50% of the time should score highest
        s = JobStats(name="test", run_count=10, failure_count=5,
                     durations=[100]*10)
        assert s.flakiness_score > 0.9

    def test_flakiness_score_low_for_always_failing(self):
        # A job that always fails is broken, not flaky
        s = JobStats(name="test", run_count=10, failure_count=10,
                     durations=[100]*10)
        assert s.flakiness_score < 0.1

    def test_flakiness_score_zero_for_always_passing(self):
        s = JobStats(name="test", run_count=10, failure_count=0,
                     durations=[100]*10)
        assert s.flakiness_score == 0.0

    def test_duration_variance(self):
        s = JobStats(name="test", durations=[100, 200])
        assert s.duration_variance > 0


class TestWorkflowAnalyzer:
    def test_loads_jobs(self, analyzer):
        assert "lint" in analyzer.jobs
        assert "test" in analyzer.jobs
        assert "deploy" in analyzer.jobs

    def test_job_dependencies_parsed(self, analyzer):
        assert analyzer.jobs["test"].needs == ["lint"]
        assert analyzer.jobs["deploy"].needs == ["test"]
        assert analyzer.jobs["lint"].needs == []

    def test_stats_computed(self, analyzer):
        assert "lint" in analyzer.stats
        assert analyzer.stats["lint"].run_count == 3
        assert analyzer.stats["test"].run_count == 3

    def test_skipped_jobs_excluded_from_stats(self, analyzer):
        # deploy was skipped in run_2 — only 2 actual runs
        assert analyzer.stats["deploy"].run_count == 2

    def test_avg_duration_lint(self, analyzer):
        # lint: 30, 28, 32 → avg = 30
        assert analyzer.stats["lint"].avg_duration == pytest.approx(30.0)

    def test_failure_rate_test_job(self, analyzer):
        # test: 1 failure out of 3 runs
        assert analyzer.stats["test"].failure_rate == pytest.approx(1/3, rel=0.01)

    def test_critical_path_is_sequential_chain(self, analyzer):
        path = analyzer.get_critical_path()
        # All 3 jobs form a single chain: lint → test → deploy
        assert path == ["lint", "test", "deploy"]

    def test_sequential_time(self, analyzer):
        # lint avg=30, test avg=120, deploy avg=62.5
        total = analyzer.get_total_sequential_time()
        assert total > 200

    def test_parallel_time_equals_sequential_for_chain(self, analyzer):
        # A pure sequential chain has no parallelism savings
        seq = analyzer.get_total_sequential_time()
        par = analyzer.get_theoretical_parallel_time()
        assert par == pytest.approx(seq, rel=0.01)

    def test_slow_jobs_threshold(self, analyzer):
        # No jobs exceed 300s avg in our sample
        slow = analyzer.get_slow_jobs(threshold_seconds=300)
        assert len(slow) == 0

    def test_slow_jobs_with_low_threshold(self, analyzer):
        slow = analyzer.get_slow_jobs(threshold_seconds=50)
        names = [s.name for s in slow]
        assert "test" in names

    def test_flaky_jobs_detection(self, analyzer):
        # test job fails 1/3 of the time → some flakiness
        flaky = analyzer.get_flaky_jobs(threshold=0.1)
        names = [s.name for s in flaky]
        assert "test" in names

    def test_no_parallelizable_groups_in_chain(self, analyzer):
        # A pure sequential chain has no parallel opportunities
        groups = analyzer.get_parallelizable_groups()
        assert groups == []


# ── Fixtures for caching / sharding / timeline tests ─────────────────────────

WORKFLOW_WITH_INSTALLS = """
name: Build and Test
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Install linters
        run: pip install flake8 black
      - name: Run lint
        run: flake8 src/
  slow-tests:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v3
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest tests/ -v
  cached-job:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          cache: pip
      - name: Run checks
        run: pip install mypy && mypy src/
"""

HISTORY_WITH_SLOW_TESTS = {
    "workflow_name": "Build and Test",
    "repo": "test/repo",
    "runs": [
        {
            "run_id": "r1", "timestamp": "2026-06-01T09:00:00Z",
            "trigger": "push", "branch": "main", "status": "success",
            "jobs": {
                "lint": {"duration_seconds": 30, "status": "success"},
                "slow-tests": {"duration_seconds": 400, "status": "success"},
                "cached-job": {"duration_seconds": 50, "status": "success"},
            },
        },
        {
            "run_id": "r2", "timestamp": "2026-06-01T11:00:00Z",
            "trigger": "push", "branch": "main", "status": "success",
            "jobs": {
                "lint": {"duration_seconds": 32, "status": "success"},
                "slow-tests": {"duration_seconds": 380, "status": "success"},
                "cached-job": {"duration_seconds": 48, "status": "success"},
            },
        },
    ],
}


@pytest.fixture
def analyzer_installs(tmp_path):
    wf = tmp_path / "workflow.yml"
    hist = tmp_path / "history.json"
    wf.write_text(WORKFLOW_WITH_INSTALLS)
    hist.write_text(json.dumps(HISTORY_WITH_SLOW_TESTS))
    a = WorkflowAnalyzer(str(wf), str(hist))
    a.load()
    return a


# ── Caching recommendations ───────────────────────────────────────────────────

class TestCachingRecommendations:
    def test_detects_pip_without_cache(self, analyzer_installs):
        recs = analyzer_installs.get_caching_recommendations()
        jobs_flagged = [r["job"] for r in recs]
        assert "lint" in jobs_flagged
        assert "slow-tests" in jobs_flagged

    def test_skips_job_with_cache_configured(self, analyzer_installs):
        recs = analyzer_installs.get_caching_recommendations()
        jobs_flagged = [r["job"] for r in recs]
        assert "cached-job" not in jobs_flagged

    def test_identifies_package_manager(self, analyzer_installs):
        recs = analyzer_installs.get_caching_recommendations()
        lint_rec = next(r for r in recs if r["job"] == "lint")
        assert "pip" in lint_rec["package_managers"]

    def test_suggestion_includes_setup_python(self, analyzer_installs):
        recs = analyzer_installs.get_caching_recommendations()
        lint_rec = next(r for r in recs if r["job"] == "lint")
        assert "setup-python" in lint_rec["suggestion"]

    def test_no_cache_recs_for_chain_without_installs(self, analyzer):
        # The base fixture workflow has no run: commands in steps (only name/uses)
        recs = analyzer.get_caching_recommendations()
        assert recs == []


# ── Sharding recommendations ──────────────────────────────────────────────────

class TestShardingRecommendations:
    def test_flags_slow_test_job(self, analyzer_installs):
        recs = analyzer_installs.get_sharding_recommendations(slow_threshold=300)
        jobs_flagged = [r["job"] for r in recs]
        assert "slow-tests" in jobs_flagged

    def test_skips_fast_jobs(self, analyzer_installs):
        recs = analyzer_installs.get_sharding_recommendations(slow_threshold=300)
        jobs_flagged = [r["job"] for r in recs]
        assert "lint" not in jobs_flagged

    def test_suggested_shards_reasonable(self, analyzer_installs):
        recs = analyzer_installs.get_sharding_recommendations(slow_threshold=300)
        rec = next(r for r in recs if r["job"] == "slow-tests")
        assert 2 <= rec["suggested_shards"] <= 8

    def test_estimated_shard_duration(self, analyzer_installs):
        recs = analyzer_installs.get_sharding_recommendations(slow_threshold=300)
        rec = next(r for r in recs if r["job"] == "slow-tests")
        expected = rec["avg_duration_seconds"] / rec["suggested_shards"]
        assert rec["estimated_shard_duration_seconds"] == pytest.approx(expected, rel=0.01)

    def test_no_sharding_recs_without_slow_jobs(self, analyzer):
        recs = analyzer.get_sharding_recommendations(slow_threshold=300)
        assert recs == []


# ── Timeline ──────────────────────────────────────────────────────────────────

class TestTimeline:
    def test_timeline_has_all_jobs(self, analyzer):
        timeline = analyzer.compute_timeline()
        assert set(timeline.keys()) == {"lint", "test", "deploy"}

    def test_root_starts_at_zero(self, analyzer):
        timeline = analyzer.compute_timeline()
        assert timeline["lint"]["start"] == 0.0

    def test_dependent_starts_after_parent_ends(self, analyzer):
        timeline = analyzer.compute_timeline()
        assert timeline["test"]["start"] >= timeline["lint"]["end"]
        assert timeline["deploy"]["start"] >= timeline["test"]["end"]

    def test_parallel_jobs_same_start(self, analyzer_installs):
        timeline = analyzer_installs.compute_timeline()
        # slow-tests and cached-job both depend on lint — should start at the same time
        assert timeline["slow-tests"]["start"] == timeline["cached-job"]["start"]

    def test_duration_matches_avg(self, analyzer):
        timeline = analyzer.compute_timeline()
        for job, times in timeline.items():
            assert times["end"] == pytest.approx(times["start"] + times["duration"], rel=0.01)


# ── GitHub Fetcher ────────────────────────────────────────────────────────────

MOCK_WORKFLOWS = {
    "workflows": [
        {"id": 1, "name": "CI Pipeline", "path": ".github/workflows/ci.yml"},
    ]
}

MOCK_RUNS = {
    "workflow_runs": [
        {
            "id": 101,
            "name": "CI Pipeline",
            "head_branch": "main",
            "event": "push",
            "conclusion": "success",
            "run_started_at": "2026-06-20T09:00:00Z",
            "created_at": "2026-06-20T09:00:00Z",
        },
        {
            "id": 102,
            "name": "CI Pipeline",
            "head_branch": "feature/x",
            "event": "pull_request",
            "conclusion": "failure",
            "run_started_at": "2026-06-21T10:00:00Z",
            "created_at": "2026-06-21T10:00:00Z",
        },
    ]
}

MOCK_JOBS_101 = {
    "jobs": [
        {
            "name": "lint",
            "conclusion": "success",
            "started_at": "2026-06-20T09:00:05Z",
            "completed_at": "2026-06-20T09:00:50Z",
            "labels": ["ubuntu-latest"],
        },
        {
            "name": "test",
            "conclusion": "success",
            "started_at": "2026-06-20T09:01:00Z",
            "completed_at": "2026-06-20T09:04:00Z",
            "labels": ["ubuntu-latest"],
        },
    ]
}

MOCK_JOBS_102 = {
    "jobs": [
        {
            "name": "lint",
            "conclusion": "success",
            "started_at": "2026-06-21T10:00:05Z",
            "completed_at": "2026-06-21T10:00:45Z",
            "labels": ["ubuntu-latest"],
        },
        {
            "name": "test",
            "conclusion": "failure",
            "started_at": "2026-06-21T10:01:00Z",
            "completed_at": "2026-06-21T10:03:30Z",
            "labels": ["ubuntu-latest"],
        },
    ]
}

MOCK_YAML_CONTENT = base64.b64encode(b"name: CI\njobs:\n  lint:\n    runs-on: ubuntu-latest\n").decode()
MOCK_FILE = {"content": MOCK_YAML_CONTENT}


def _make_fetcher_with_mock(responses):
    """Build a GitHubFetcher whose _get() returns responses in order."""
    fetcher = GitHubFetcher("myorg/myapp", token="test_token", workflow_name="CI Pipeline")
    call_iter = iter(responses)
    fetcher._get = lambda url: next(call_iter)
    return fetcher


class TestGitHubFetcher:
    def test_resolve_workflow_by_name(self):
        fetcher = _make_fetcher_with_mock([MOCK_WORKFLOWS])
        wf_id, wf_path = fetcher._resolve_workflow()
        assert wf_id == "1"
        assert wf_path == ".github/workflows/ci.yml"

    def test_resolve_workflow_not_found_raises(self):
        fetcher = GitHubFetcher("myorg/myapp", workflow_name="nonexistent")
        fetcher._get = lambda url: MOCK_WORKFLOWS
        with pytest.raises(ValueError, match="not found"):
            fetcher._resolve_workflow()

    def test_fetch_run_history_structure(self):
        fetcher = _make_fetcher_with_mock([
            MOCK_WORKFLOWS, MOCK_RUNS, MOCK_JOBS_101, MOCK_JOBS_102
        ])
        history = fetcher.fetch_run_history(max_runs=10)
        assert history["repo"] == "myorg/myapp"
        assert history["workflow_name"] == "CI Pipeline"
        assert len(history["runs"]) == 2

    def test_run_status_mapped_correctly(self):
        fetcher = _make_fetcher_with_mock([
            MOCK_WORKFLOWS, MOCK_RUNS, MOCK_JOBS_101, MOCK_JOBS_102
        ])
        history = fetcher.fetch_run_history()
        statuses = [r["status"] for r in history["runs"]]
        assert "success" in statuses
        assert "failure" in statuses

    def test_job_duration_computed(self):
        fetcher = _make_fetcher_with_mock([
            MOCK_WORKFLOWS, MOCK_RUNS, MOCK_JOBS_101, MOCK_JOBS_102
        ])
        history = fetcher.fetch_run_history()
        lint = history["runs"][0]["jobs"]["lint"]
        assert lint["duration_seconds"] == 45  # 09:00:05 → 09:00:50

    def test_skipped_job_mapped(self):
        jobs_with_skip = {
            "jobs": [{
                "name": "deploy",
                "conclusion": "skipped",
                "started_at": None,
                "completed_at": None,
                "labels": ["ubuntu-latest"],
            }]
        }
        result = GitHubFetcher._convert_job(jobs_with_skip["jobs"][0])
        assert result["status"] == "skipped"
        assert result["duration_seconds"] == 0

    def test_fetch_all_returns_yaml_and_history(self):
        fetcher = _make_fetcher_with_mock([
            MOCK_WORKFLOWS, MOCK_FILE, MOCK_RUNS, MOCK_JOBS_101, MOCK_JOBS_102
        ])
        history, yaml_text = fetcher.fetch_all(max_runs=10)
        assert "name: CI" in yaml_text
        assert len(history["runs"]) == 2

    def test_no_token_still_works(self):
        fetcher = GitHubFetcher("myorg/myapp")
        fetcher._get = lambda url: MOCK_WORKFLOWS
        wf_id, _ = fetcher._resolve_workflow()
        assert wf_id == "1"


def test_invalid_dependency_graphs_fail_explicitly():
    from analyzer import WorkflowJob
    a=WorkflowAnalyzer("unused","unused")
    assert a.get_critical_path()==[]
    a.jobs={"x":WorkflowJob("x",["y"]),"y":WorkflowJob("y",["x"])}
    with pytest.raises(ValueError,match="cycle"): a.get_critical_path()
    a.jobs={"x":WorkflowJob("x",["missing"])}
    with pytest.raises(ValueError,match="unknown"): a.get_critical_path()
