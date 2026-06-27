"""
CI Pipeline Optimizer — FastAPI Web Interface
----------------------------------------------
Exposes the analyzer as a REST API so it can be:
  - Integrated as a GitHub Actions step
  - Called from a web dashboard
  - Used as a Render-deployed demo
"""

import json
import os
import sys
import tempfile
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
from analyzer import WorkflowAnalyzer
from reporter import generate_json_report

app = FastAPI(
    title="CI Pipeline Optimizer",
    description="Analyze GitHub Actions pipelines to find bottlenecks, flaky tests, and parallelization wins.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    workflow_yaml: str
    run_history: dict
    flaky_threshold: float = 0.2
    slow_threshold_seconds: float = 300


@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html>
    <head>
        <title>CI Pipeline Optimizer</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                   max-width: 800px; margin: 60px auto; padding: 20px; background: #0d1117; color: #e6edf3; }
            h1 { color: #58a6ff; }
            h2 { color: #79c0ff; border-bottom: 1px solid #30363d; padding-bottom: 8px; }
            code { background: #161b22; padding: 2px 6px; border-radius: 4px; color: #f0883e; }
            pre { background: #161b22; padding: 16px; border-radius: 8px; overflow-x: auto; border: 1px solid #30363d; }
            .badge { background: #238636; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px; }
            a { color: #58a6ff; }
        </style>
    </head>
    <body>
        <h1>⚡ CI Pipeline Optimizer</h1>
        <p>
            <span class="badge">v1.0.0</span>&nbsp;
            Built to address <strong>"Code validation is the next big bottleneck"</strong>
        </p>

        <h2>What it does</h2>
        <p>Analyzes your GitHub Actions pipeline to surface:</p>
        <ul>
            <li>🐢 <strong>Slow jobs</strong> — above configurable duration threshold</li>
            <li>🎲 <strong>Flaky tests</strong> — unpredictable pass/fail patterns</li>
            <li>🔗 <strong>Critical path</strong> — your true CI bottleneck chain</li>
            <li>⚡ <strong>Parallelization wins</strong> — jobs that can run concurrently</li>
        </ul>

        <h2>API Endpoints</h2>
        <pre>POST /analyze       — Analyze workflow + run history JSON
GET  /health        — Health check
GET  /sample        — Run analysis on built-in sample data
GET  /docs          — Interactive Swagger UI</pre>

        <h2>Quick Start</h2>
        <pre>curl -X POST https://ci-optimizer.onrender.com/analyze \\
  -H "Content-Type: application/json" \\
  -d '{
    "workflow_yaml": "...",
    "run_history": { "runs": [...] }
  }'</pre>

        <p>
            <a href="/docs">📖 Interactive API Docs</a> &nbsp;|&nbsp;
            <a href="/sample">▶ Run Sample Analysis</a> &nbsp;|&nbsp;
            <a href="/health">💚 Health Check</a>
        </p>
    </body>
    </html>
    """


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ci-pipeline-optimizer", "version": "1.0.0"}


@app.post("/analyze")
async def analyze(request: AnalyzeRequest):
    """
    Analyze a GitHub Actions workflow and run history.
    Returns optimization report with bottlenecks, flaky tests, and recommendations.
    """
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as wf:
            wf.write(request.workflow_yaml)
            workflow_path = wf.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as hf:
            json.dump(request.run_history, hf)
            history_path = hf.name

        analyzer = WorkflowAnalyzer(workflow_path, history_path)
        analyzer.load()

        report = generate_json_report(analyzer)

        os.unlink(workflow_path)
        os.unlink(history_path)

        return report

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/sample")
async def sample():
    """Run analysis on the built-in sample data."""
    sample_dir = os.path.join(os.path.dirname(__file__), '..', 'sample_data')
    workflow_path = os.path.join(sample_dir, 'workflow.yml')
    history_path = os.path.join(sample_dir, 'run_history.json')

    if not os.path.exists(workflow_path):
        raise HTTPException(status_code=404, detail="Sample data not found")

    analyzer = WorkflowAnalyzer(workflow_path, history_path)
    analyzer.load()
    return generate_json_report(analyzer)
