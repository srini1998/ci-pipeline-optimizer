import { parseDocument } from 'yaml';

export function parseWorkflow(text, recording = null) {
  if (typeof text !== 'string' || !text.trim() || text.length > 60000) throw new Error('Paste 1–60,000 characters of workflow YAML.');
  const doc = parseDocument(text, { uniqueKeys: true });
  if (doc.errors.length) throw new Error('Invalid YAML: ' + doc.errors[0].message.split('\n')[0]);
  const data = doc.toJS({ maxAliasCount: 0 });
  if (!data?.jobs || typeof data.jobs !== 'object' || Array.isArray(data.jobs)) throw new Error('Workflow needs a jobs mapping.');
  const entries = Object.entries(data.jobs);
  if (!entries.length || entries.length > 100) throw new Error('Use 1–100 workflow jobs.');
  const jobs = entries.map(([id, raw]) => {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error(`Invalid job ${id}.`);
    const needs = raw.needs === undefined ? [] : typeof raw.needs === 'string' ? [raw.needs] : raw.needs;
    if (!Array.isArray(needs) || needs.some(n => typeof n !== 'string') || needs.length > 100) throw new Error(`Invalid needs for ${id}.`);
    if (needs.some(n => n.includes('${{'))) throw new Error('Dynamic needs expressions are unsupported.');
    const steps = Array.isArray(raw.steps) ? raw.steps.filter(s => s && typeof s === 'object') : [];
    const source = steps.map(s => `${s.name ?? ''} ${s.run ?? ''}`).join('\n');
    const hasCache = steps.some(s => /actions\/cache@/.test(s.uses ?? '') || (s.with?.cache && /setup-(node|python|java|go)/.test(s.uses ?? '')));
    const install = /npm (ci|install)|pip\d? install|yarn|pnpm install|go mod download|cargo fetch/.test(source);
    const test = /\b(test|tests|pytest|jest|vitest|mocha)\b/i.test(`${id} ${source}`);
    const template = String(raw.name ?? id);
    const parts = template.split(/\$\{\{[^}]+\}\}/).map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const namePattern = new RegExp('^' + parts.join('.+?') + '(?: \\(.*\\))?$');
    const observed = recording?.jobs.filter(j => namePattern.test(j.name) || j.name === id) ?? [];
    const seconds = observed.length ? Math.max(...observed.map(j => j.seconds)) : 60;
    const installSeconds = observed.length ? Math.max(...observed.map(j => j.steps.filter(s => /install|npm ci|setup-node|setup-python|pnpm|yarn/i.test(s.name)).reduce((s,x) => s+x.seconds,0))) : seconds * 0.2;
    return { id, needs: [...new Set(needs)], seconds, measured: !!observed.length, observed: observed.map(j => j.name), matrix: !!raw.strategy?.matrix, conditional: !!raw.if, hasCache, install, test, installSeconds, reusable: !!raw.uses };
  });
  schedule(jobs);
  return jobs;
}

export function schedule(jobs) {
  const byId = new Map(jobs.map(j => [j.id, j]));
  if (byId.size !== jobs.length) throw new Error('Duplicate job id.');
  const done = new Map(), active = new Set();
  function visit(id) {
    if (done.has(id)) return done.get(id);
    if (!byId.has(id)) throw new Error('Unknown dependency: ' + id);
    if (active.has(id)) throw new Error('Dependency cycle: ' + id);
    const job = byId.get(id);
    if (!Number.isFinite(job.seconds) || job.seconds < 0 || job.seconds > 86400) throw new Error('Job durations must be finite, 0–86,400 seconds.');
    active.add(id);
    const parents = job.needs.map(visit);
    const latest = parents.reduce((a,b) => !a || b.end > a.end ? b : a, null);
    const start = latest?.end ?? 0;
    const row = { ...job, start, end: start + job.seconds, path: [...(latest?.path ?? []), id] };
    active.delete(id); done.set(id, row); return row;
  }
  const rows = jobs.map(j => visit(j.id));
  const last = rows.reduce((a,b) => !a || b.end > a.end ? b : a, null);
  return { rows, seconds: last?.end ?? 0, path: last?.path ?? [], runnerSeconds: jobs.reduce((s,j) => s+j.seconds,0) };
}

export function simulate(jobs, { shards = 1, cache = false, cacheSaving = 0.5, overhead = 15 } = {}) {
  if (!Number.isInteger(shards) || shards < 1 || shards > 8 || !Number.isFinite(cacheSaving) || cacheSaving < 0 || cacheSaving > 1 || !Number.isFinite(overhead) || overhead < 0 || overhead > 300) throw new Error('Invalid simulation assumptions.');
  let runnerSeconds = 0;
  const changed = jobs.map(j => {
    const setup = Math.min(j.seconds, j.installSeconds ?? 0);
    const saved = cache && j.install && !j.hasCache ? setup * cacheSaving : 0;
    const n = j.test ? shards : 1;
    const seconds = n > 1 ? setup - saved + (j.seconds - setup) / n + overhead : j.seconds - saved;
    runnerSeconds += seconds * n;
    return { ...j, seconds, originalSeconds: j.seconds, shards: n, saved };
  });
  return { ...schedule(changed), runnerSeconds };
}
