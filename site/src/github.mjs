export function repoName(value) {
  const s = String(value).trim().replace(/^https:\/\/github\.com\//, '').replace(/\/$/, '');
  if (!/^[A-Za-z0-9_.-]{1,100}\/[A-Za-z0-9_.-]{1,100}$/.test(s) || s.includes('..')) throw new Error('Use a public owner/repo or https://github.com/owner/repo.');
  return s;
}
export async function fetchRun(input, fetcher = fetch) {
  const repo = repoName(input);
  let requests = 0;
  async function get(path) {
    if (++requests > 4) throw new Error('Four-request fetch bound reached.');
    const r = await fetcher('https://api.github.com/repos/' + repo + path, { headers: { Accept: 'application/vnd.github+json' }, signal: AbortSignal.timeout(15000) });
    if (!r.ok) throw new Error(r.status === 403 || r.status === 429 ? 'GitHub free API limit reached. Use a cached recording; no paid fallback.' : `GitHub HTTP ${r.status}. Try a cached recording.`);
    const text = await r.text();
    if (text.length > 2_000_000) throw new Error('GitHub response exceeds the 2 MB bound.');
    return JSON.parse(text);
  }
  const workflows = await get('/actions/workflows?per_page=100');
  const active = (workflows.workflows ?? []).filter(w => w.state === 'active');
  const workflow = active.find(w => /^(ci|tests?|build)(\b|[-_. ])/i.test(w.name) && !/release|scorecard/i.test(w.name)) ?? active[0];
  if (!workflow) throw new Error('No active public workflows.');
  const list = await get(`/actions/workflows/${workflow.id}/runs?per_page=5&status=success`);
  const run = list.workflow_runs?.find(r => r.path?.startsWith('.github/workflows/') && r.head_sha);
  if (!run) throw new Error('No successful public workflow run found in the latest five.');
  const data = await get(`/actions/runs/${run.id}/jobs?per_page=100`);
  if (data.total_count > 100) throw new Error('This run has more than 100 jobs; choose a smaller workflow.');
  const file = await get('/contents/' + run.path.split('/').map(encodeURIComponent).join('/') + '?ref=' + run.head_sha);
  const yaml = new TextDecoder().decode(Uint8Array.from(atob(file.content.replace(/\s/g, '')), c => c.charCodeAt(0)));
  if (yaml.length > 60000) throw new Error('Workflow exceeds 60,000 characters.');
  const jobs = data.jobs.filter(j => j.started_at && j.completed_at && j.conclusion !== 'skipped').map(j => ({ name: j.name, conclusion: j.conclusion, start: j.started_at, end: j.completed_at, seconds: Math.max(0, (Date.parse(j.completed_at) - Date.parse(j.started_at)) / 1000), url: j.html_url, steps: (j.steps ?? []).map(s => ({ name: s.name, seconds: s.started_at && s.completed_at ? Math.max(0, (Date.parse(s.completed_at) - Date.parse(s.started_at)) / 1000) : 0 })) }));
  if (!jobs.length) throw new Error('No completed jobs with timings.');
  return { repo, name: run.name, runId: run.id, url: run.html_url, sha: run.head_sha, capturedAt: new Date().toISOString(), runAt: run.created_at, yaml, jobs, requests };
}
