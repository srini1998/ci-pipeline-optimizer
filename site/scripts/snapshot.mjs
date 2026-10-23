import { writeFile } from 'node:fs/promises';
import { fetchRun } from '../src/github.mjs';
const snapshots = [];
for (const repo of ['sindresorhus/p-limit', 'pallets/click', 'expressjs/express']) {
  try { const r = await fetchRun(repo); snapshots.push(r); console.log(repo, r.runId, r.jobs.length, 'jobs'); }
  catch (e) { console.error(repo, e.message); }
}
if (!snapshots.length) throw new Error('No real snapshots captured');
await writeFile(new URL('../src/snapshots.json', import.meta.url), JSON.stringify(snapshots, null, 2));
