"""
Report Generator
----------------
Takes analyzer output and produces:
  - A human-readable terminal report
  - A structured JSON report for dashboards / integrations
"""

import json
from datetime import datetime
from typing import Dict, List

from analyzer import WorkflowAnalyzer, JobStats


SEVERITY_COLORS = {
    "critical": "\033[91m",   # Red
    "warning":  "\033[93m",   # Yellow
    "info":     "\033[94m",   # Blue
    "success":  "\033[92m",   # Green
    "reset":    "\033[0m",
    "bold":     "\033[1m",
}


def colorize(text: str, color: str) -> str:
    c = SEVERITY_COLORS.get(color, "")
    reset = SEVERITY_COLORS["reset"]
    return f"{c}{text}{reset}"


def seconds_to_human(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs:02d}s"


def generate_ascii_timeline(analyzer: WorkflowAnalyzer, bar_width: int = 52) -> str:
    """ASCII Gantt chart of the optimal parallel job schedule."""
    timeline = analyzer.compute_timeline()
    if not timeline:
        return ""

    critical_set = set(analyzer.get_critical_path())
    total_time = max(t["end"] for t in timeline.values())
    if total_time == 0:
        return ""

    scale = total_time / bar_width
    name_width = max(len(n) for n in timeline) + 2

    lines = [colorize("\n📅 JOB TIMELINE (optimal parallel schedule)", "bold")]
    lines.append(f"  Total wall-clock time : {colorize(seconds_to_human(total_time), 'success')}")
    lines.append(f"  Scale                 : each block ≈ {seconds_to_human(scale)}")
    lines.append("")

    for job, times in sorted(timeline.items(), key=lambda x: x[1]["start"]):
        start_chars = int(times["start"] / scale)
        dur_chars = max(1, round(times["duration"] / scale))
        is_critical = job in critical_set
        char = "█" if is_critical else "▓"
        color = "critical" if is_critical else "info"
        bar = " " * start_chars + colorize(char * dur_chars, color)
        suffix = colorize("  ◄ critical", "critical") if is_critical else ""
        lines.append(f"  {job:{name_width}} {bar}  {seconds_to_human(times['duration'])}{suffix}")

    return "\n".join(lines)


def generate_terminal_report(analyzer: WorkflowAnalyzer) -> str:
    lines = []
    sep = "=" * 62

    lines.append(colorize(sep, "bold"))
    lines.append(colorize("  CI PIPELINE OPTIMIZATION REPORT", "bold"))
    lines.append(colorize(f"  Repo: {analyzer.history.get('repo', 'unknown')}", "info"))
    lines.append(colorize(f"  Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", "info"))
    lines.append(colorize(sep, "bold"))

    # ── SUMMARY ──────────────────────────────────────────────
    lines.append(colorize("\n📊 PIPELINE SUMMARY", "bold"))
    total_runs = len(analyzer.history.get("runs", []))
    successful = sum(1 for r in analyzer.history.get("runs", []) if r["status"] == "success")
    lines.append(f"  Total runs analyzed : {total_runs}")
    lines.append(f"  Successful runs     : {successful} ({successful/total_runs*100:.0f}%)")
    lines.append(f"  Failed runs         : {total_runs - successful}")

    seq_time = analyzer.get_total_sequential_time()
    par_time = analyzer.get_theoretical_parallel_time()
    savings = seq_time - par_time
    pct = (savings / seq_time * 100) if seq_time > 0 else 0

    lines.append(f"\n  Sequential time     : {colorize(seconds_to_human(seq_time), 'warning')}")
    lines.append(f"  Optimal parallel    : {colorize(seconds_to_human(par_time), 'success')}")
    lines.append(f"  Potential savings   : {colorize(seconds_to_human(savings) + f' ({pct:.0f}%)', 'success')}")

    # ── CRITICAL PATH ─────────────────────────────────────────
    lines.append(colorize("\n🔗 CRITICAL PATH (bottleneck chain)", "bold"))
    path = analyzer.get_critical_path()
    path_str = " → ".join(path)
    lines.append(f"  {path_str}")
    for job in path:
        stat = analyzer.stats.get(job)
        if stat:
            lines.append(f"    • {job:25s} avg {seconds_to_human(stat.avg_duration)}")

    # ── JOB TIMING TABLE ──────────────────────────────────────
    lines.append(colorize("\n⏱  JOB TIMING BREAKDOWN", "bold"))
    lines.append(f"  {'Job':<25} {'Avg':>8} {'Min':>8} {'Max':>8} {'Variance':>10} {'Runs':>6}")
    lines.append("  " + "-" * 67)
    for job_name, stat in sorted(analyzer.stats.items(), key=lambda x: x[1].avg_duration, reverse=True):
        avg_str = seconds_to_human(stat.avg_duration)
        color = "critical" if stat.avg_duration > 300 else ("warning" if stat.avg_duration > 120 else "success")
        lines.append(
            f"  {job_name:<25} {colorize(f'{avg_str:>8}', color)} "
            f"{seconds_to_human(stat.min_duration):>8} "
            f"{seconds_to_human(stat.max_duration):>8} "
            f"{'±' + seconds_to_human(stat.duration_variance):>10} "
            f"{stat.run_count:>6}"
        )

    # ── FLAKY TESTS ───────────────────────────────────────────
    flaky = analyzer.get_flaky_jobs(threshold=0.1)
    lines.append(colorize("\n🎲 FLAKY JOB DETECTION", "bold"))
    if flaky:
        lines.append(f"  {'Job':<25} {'Flakiness':>10} {'Failure Rate':>14} {'Runs':>6}")
        lines.append("  " + "-" * 58)
        for stat in flaky:
            score_color = "critical" if stat.flakiness_score > 0.4 else "warning"
            score_str = f"{stat.flakiness_score:.3f}"
            lines.append(
                f"  {stat.name:<25} "
                f"{colorize(score_str, score_color):>10} "
                f"{stat.failure_rate*100:>13.1f}% "
                f"{stat.run_count:>6}"
            )
        lines.append(colorize("\n  ⚠  Flaky jobs create unpredictable CI — fix before optimizing speed.", "warning"))
    else:
        lines.append(colorize("  ✓ No significantly flaky jobs detected.", "success"))

    # ── PARALLELIZATION OPPORTUNITIES ─────────────────────────
    parallel_groups = analyzer.get_parallelizable_groups()
    lines.append(colorize("\n⚡ PARALLELIZATION OPPORTUNITIES", "bold"))
    if parallel_groups:
        for group in parallel_groups:
            group_time = sum(analyzer.stats.get(j, JobStats(j)).avg_duration for j in group)
            max_time = max(analyzer.stats.get(j, JobStats(j)).avg_duration for j in group)
            savings_p = group_time - max_time
            lines.append(f"  Jobs that share the same dependencies → can run in parallel:")
            for j in group:
                lines.append(f"    • {j}")
            lines.append(colorize(f"    → Saves ~{seconds_to_human(savings_p)} per run\n", "success"))
    else:
        lines.append("  No additional parallelization opportunities found.")

    # ── TIMELINE ──────────────────────────────────────────────
    lines.append(generate_ascii_timeline(analyzer))

    # ── RECOMMENDATIONS ───────────────────────────────────────
    lines.append(colorize("\n💡 RECOMMENDATIONS", "bold"))
    recs = _generate_recommendations(analyzer)
    for i, rec in enumerate(recs, 1):
        lines.append(f"  {i}. {rec}")

    lines.append(colorize("\n" + sep, "bold"))
    return "\n".join(lines)


def _generate_recommendations(analyzer: WorkflowAnalyzer) -> List[str]:
    recs = []

    slow = analyzer.get_slow_jobs(threshold_seconds=300)
    for s in slow:
        recs.append(
            f"[SLOW] '{s.name}' averages {seconds_to_human(s.avg_duration)} — "
            f"consider splitting into parallel shards or adding caching."
        )

    flaky = analyzer.get_flaky_jobs(threshold=0.2)
    for s in flaky:
        recs.append(
            f"[FLAKY] '{s.name}' has flakiness score {s.flakiness_score:.2f} — "
            f"investigate race conditions, timeouts, or non-deterministic test data."
        )

    parallel_groups = analyzer.get_parallelizable_groups()
    for group in parallel_groups:
        recs.append(
            f"[PARALLEL] {', '.join(group)} have identical dependencies — "
            f"confirm they are already running in parallel in your workflow."
        )

    for job_name, stat in analyzer.stats.items():
        if stat.duration_variance > 60:
            recs.append(
                f"[VARIANCE] '{job_name}' has high duration variance (±{seconds_to_human(stat.duration_variance)}) — "
                f"likely caused by network I/O or cold runner provisioning. Add dependency caching."
            )

    for rec in analyzer.get_caching_recommendations():
        recs.append(
            f"[CACHE] '{rec['job']}' installs {', '.join(rec['package_managers'])} on every run "
            f"without caching — {rec['suggestion']}."
        )

    for rec in analyzer.get_sharding_recommendations():
        recs.append(
            f"[SHARD] '{rec['job']}' averages {seconds_to_human(rec['avg_duration_seconds'])} — "
            f"split into {rec['suggested_shards']} matrix shards "
            f"(~{seconds_to_human(rec['estimated_shard_duration_seconds'])} each)."
        )

    if not recs:
        recs.append("Pipeline looks healthy! No critical issues detected.")

    return recs


def generate_json_report(analyzer: WorkflowAnalyzer) -> Dict:
    """Machine-readable JSON report for dashboards or GitHub Actions output."""
    flaky = analyzer.get_flaky_jobs(threshold=0.1)
    slow = analyzer.get_slow_jobs(threshold_seconds=300)
    path = analyzer.get_critical_path()

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "repo": analyzer.history.get("repo"),
        "workflow": analyzer.history.get("workflow_name"),
        "summary": {
            "total_runs": len(analyzer.history.get("runs", [])),
            "sequential_time_seconds": round(analyzer.get_total_sequential_time(), 1),
            "optimal_parallel_time_seconds": round(analyzer.get_theoretical_parallel_time(), 1),
            "potential_savings_seconds": round(
                analyzer.get_total_sequential_time() - analyzer.get_theoretical_parallel_time(), 1
            ),
        },
        "critical_path": path,
        "jobs": {
            name: {
                "avg_duration_seconds": round(s.avg_duration, 1),
                "min_duration_seconds": round(s.min_duration, 1),
                "max_duration_seconds": round(s.max_duration, 1),
                "duration_variance_seconds": round(s.duration_variance, 1),
                "failure_rate": round(s.failure_rate, 3),
                "flakiness_score": s.flakiness_score,
                "run_count": s.run_count,
            }
            for name, s in analyzer.stats.items()
        },
        "flaky_jobs": [
            {"name": s.name, "flakiness_score": s.flakiness_score, "failure_rate": round(s.failure_rate, 3)}
            for s in flaky
        ],
        "slow_jobs": [
            {"name": s.name, "avg_duration_seconds": round(s.avg_duration, 1)}
            for s in slow
        ],
        "parallelization_opportunities": analyzer.get_parallelizable_groups(),
        "timeline": analyzer.compute_timeline(),
        "caching_recommendations": analyzer.get_caching_recommendations(),
        "sharding_recommendations": analyzer.get_sharding_recommendations(),
        "recommendations": _generate_recommendations(analyzer),
    }
