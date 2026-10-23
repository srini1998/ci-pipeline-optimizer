import './style.css';
import snapshots from './snapshots.json';
import { parseWorkflow, schedule, simulate } from './engine.mjs';
import { fetchRun } from './github.mjs';
const $ = s => document.querySelector(s);
const esc = v => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = n => n >= 60 ? `${Math.floor(n/60)}m ${Math.round(n%60)}s` : `${Math.round(n)}s`;
const demo = `name: Fork and join study\non: [push]\njobs:\n  lint:\n    steps:\n      - run: npm ci && npm run lint\n  tests:\n    needs: lint\n    steps:\n      - run: npm ci && npm test\n  build:\n    needs: lint\n    steps:\n      - run: npm ci && npm run build\n  release:\n    needs: [tests, build]\n    steps:\n      - run: echo ready\n`;
let recording = null, jobs = [], currentSource = '', loadedAt = 0, loading = false;
$('#app').innerHTML = `<div class="sheet"><header><a class="brand" href="#">BUILD<br><strong>SHEET</strong><span class="brand-mark">↗</span></a><p class="purpose">Find the job holding up your build.<br>Then test a faster arrangement.</p><div class="titleblock">CI TIMING WORKBENCH<br>GITHUB ACTIONS / READ ONLY<br>NO RUNNERS STARTED</div></header>
<main><section class="intake" aria-labelledby="intake"><div class="section-line"><h1 id="intake">Start with an observed run</h1><span>01 / INPUT</span></div><div class="recordings">${snapshots.map((s,i)=>`<button class="record" data-record="${i}"><span>RECORDED PUBLIC RUN</span><strong>${esc(s.repo)}</strong><small>${esc(s.name)} · ${s.jobs.length} jobs</small></button>`).join('')}<button class="record study" id="study"><span>SYNTHETIC STUDY</span><strong>Fork + join</strong><small>Four jobs, one bottleneck</small></button></div></section>
<div class="workspace"><aside><section class="panel"><h2>Bring your own repository</h2><form id="fetch"><label for="repo">Public GitHub owner/repo</label><div class="fetch-row"><input id="repo" placeholder="sindresorhus/p-limit" maxlength="210" required><button id="fetch-button">Fetch</button></div></form><p class="note">Four unauthenticated GitHub requests at most. Your IP’s free limit applies. Results are never substituted with a recording.</p></section>
<section class="panel"><h2>Revise the workflow</h2><label for="yaml">GitHub Actions YAML</label><textarea id="yaml" spellcheck="false" maxlength="60000" rows="10"></textarea><button id="analyse" class="primary">Draw this workflow ↗</button><p class="note">Edited YAML has no observed timings. Set estimates below; YAML is parsed, never executed.</p></section>
<section class="panel"><h2>Simulation assumptions</h2><label for="shards">Test shards <output id="shards-value">1</output></label><input type="range" id="shards" min="1" max="8" value="1"><label for="overhead">Overhead per shard (seconds)</label><input id="overhead" type="number" min="0" max="300" value="15"><label class="check"><input id="cache" type="checkbox"> Add caching where missing</label><label for="saving">Install/setup time avoided <output id="saving-value">50%</output></label><input type="range" id="saving" min="0" max="90" value="50"><p class="note">Even test split; setup repeats on every shard. Savings are hypotheses, never measured improvements.</p></section></aside>
<div class="drawing"><div id="status" role="status" aria-live="polite"></div><p id="error" role="alert" hidden></p><section class="summary" aria-label="Duration comparison"><span class="label">DEPENDENCY LOWER BOUND → SIMULATED</span><div class="measurement"><strong id="before">0s</strong><span class="arrow">→</span><strong id="after">0s</strong></div><p id="delta"></p><div class="stats"><span id="runner"></span><span id="critical"></span></div></section>
<section class="gantt-panel"><div class="section-line"><h2>Job schematic</h2><span>02 / TIMELINE</span></div><p class="legend"><span class="key baseline"></span> baseline <span class="key proposed"></span> simulated <span>★ critical path</span></p><div class="gantt-scroll" tabindex="0" role="region" aria-label="Scrollable job timeline"><div id="gantt"></div></div><p class="note">Earliest starts, unlimited runners. Queue delays and runner contention excluded. Matrix groups use their slowest observed child; extra shard runner time is approximate for matrix jobs.</p></section>
<section class="recommendations"><div class="section-line"><h2>Notes on the drawing</h2><span>03 / REVIEW</span></div><div id="recommendations"></div></section>
<details class="panel" id="duration-panel"><summary>Inspect timings & adjust estimates</summary><div id="durations"></div></details>
<details class="panel"><summary>Observed job evidence</summary><div id="evidence"></div></details>
<section class="limits"><h2>What this drawing leaves out</h2><p>One successful run is a sample, not a performance guarantee or flakiness measurement. Cache hits and even test splits need measurement in your repository. Conditions, concurrency groups, matrix limits and reusable workflows are not executed; skipped or unmatched jobs need explicit estimates. No workflow is changed or dispatched.</p></section></div></div></main>
<footer><span>BUILD SHEET / DEPENDENCIES BEFORE DECORATION</span><a href="https://github.com/srini1998/ci-pipeline-optimizer">Source & checks ↗</a><a href="https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api">GitHub API limits ↗</a></footer></div>`;
function showError(e) { $('#error').hidden = !e; $('#error').textContent = e?.message ?? ''; }
function load(yaml, rec, source) {
  const parsed = parseWorkflow(yaml, rec);
  jobs = parsed; recording = rec; currentSource = source;
  $('#yaml').value = yaml; showError(null); $('#status').textContent = source;
  $('#durations').innerHTML = jobs.map((j,i)=>`<label class="duration-row">${esc(j.id)} <small>${j.measured?'observed envelope':'assumed, edit me'}</small><input aria-label="Seconds for ${esc(j.id)}" type="number" min="0" max="86400" step="1" value="${j.seconds}" data-duration="${i}"></label>`).join('');
  $('#evidence').innerHTML = rec ? `<p>Captured ${esc(rec.capturedAt)} · run ${esc(rec.runAt)}<br>Commit <code>${esc(rec.sha)}</code></p><a href="${esc(rec.url)}" target="_blank" rel="noreferrer">Open original run ↗</a><div class="observed">${rec.jobs.map(j=>`<p><a href="${esc(j.url)}" target="_blank" rel="noreferrer">${esc(j.name)}</a> <strong>${time(j.seconds)}</strong><small>${esc(j.start)} → ${esc(j.end)}</small></p>`).join('')}</div>` : '<p>Synthetic or user-entered estimates. No external timing claim.</p>';
  document.querySelectorAll('[data-record]').forEach(b=>b.classList.toggle('selected',rec===snapshots[Number(b.dataset.record)]));
  render();
}
function render() {
  try {
    const shards = +$('#shards').value, saving = +$('#saving').value;
    $('#shards-value').value = shards; $('#saving-value').value = saving+'%';
    const baseline = schedule(jobs), next = simulate(jobs,{shards,cache:$('#cache').checked,cacheSaving:saving/100,overhead:+$('#overhead').value});
    const max = Math.max(baseline.seconds,next.seconds,1), critical = new Set(baseline.path);
    $('#before').textContent = time(baseline.seconds); $('#after').textContent = time(next.seconds);
    const delta = baseline.seconds-next.seconds;
    $('#delta').textContent = delta > 0 ? `${time(delta)} shorter (${baseline.seconds?Math.round(delta/baseline.seconds*100):0}%). Simulated, not a measured speedup.` : delta < 0 ? `${time(-delta)} longer. Duplicated setup can outweigh sharding.` : 'No change under these assumptions. Move a control to test an alternative.';
    $('#runner').textContent = `Template runner time: ${time(baseline.runnerSeconds)} → ${time(next.runnerSeconds)}`;
    $('#critical').textContent = 'Critical chain: '+baseline.path.join(' → ');
    $('#gantt').innerHTML = `<div class="axis"><span>JOB / NEEDS</span><div>${[0,.25,.5,.75,1].map(x=>`<span style="left:${x*100}%">${time(x*max)}</span>`).join('')}</div></div>` + baseline.rows.map((j,i)=>{const n=next.rows[i];return `<div class="gantt-row ${critical.has(j.id)?'critical':''}"><div class="job-name"><strong>${critical.has(j.id)?'★ ':''}${esc(j.id)}</strong><small>← ${esc(j.needs.join(', ')||'start')} ${j.matrix?' / matrix':''}</small></div><div class="track"><div class="job-bar before" style="left:${j.start/max*100}%;width:${Math.max(.3,j.seconds/max*100)}%" title="Baseline ${time(j.seconds)}"></div><div class="job-bar after" style="left:${n.start/max*100}%;width:${Math.max(.3,n.seconds/max*100)}%" title="Simulated ${time(n.seconds)}"></div><span class="duration-note">${time(j.seconds)} → ${time(n.seconds)}</span></div></div>`}).join('');
    const notes=[];
    for(const j of jobs){if(j.install&&!j.hasCache)notes.push(`<article><span>CACHE / ${esc(j.id)}</span><h3>Reuse dependencies before rebuilding.</h3><p>No recognised setup-action cache found. Simulation can avoid a chosen share of ${time(j.installSeconds)} of install/setup time. Verify restore keys and actual hit rate.</p></article>`);if(j.test)notes.push(`<article><span>SHARD / ${esc(j.id)}</span><h3>Split tests, account for setup.</h3><p>Try 2–8 balanced shards. Each repeats setup plus the configured overhead. Reusable, integration or stateful tests may need isolation first.</p></article>`);}
    const unmatched=jobs.filter(j=>!j.measured).map(j=>j.id);
    if(unmatched.length)notes.unshift(`<article class="caution"><span>ASSUMED TIMINGS</span><p>${esc(unmatched.join(', '))}: defaults or edits, not measured. Adjust them before using the drawing.</p></article>`);
    if(jobs.some(j=>j.matrix||j.conditional||j.reusable))notes.push('<article><span>MODEL BOUNDARY</span><p>Matrix groups are collapsed. Conditions and reusable workflows are not evaluated. The dependency chart is a lower-bound model, not a scheduler replay.</p></article>');
    $('#recommendations').innerHTML=notes.join('')||'<p>No cache or test-sharding opportunity detected. A small workflow may already be efficient.</p>';
    showError(null);
  } catch(e){showError(e)}
}
for(const el of document.querySelectorAll('[data-record]'))el.onclick=()=>load(snapshots[+el.dataset.record].yaml,snapshots[+el.dataset.record],`Cached public recording · ${snapshots[+el.dataset.record].repo} · ${snapshots[+el.dataset.record].name}`);
$('#study').onclick=()=>{load(demo,null,'Synthetic fork-and-join study · authored timings, not a recorded run');jobs.forEach((j,i)=>{j.seconds=[30,300,100,20][i];j.installSeconds=j.install?60:0});$('#durations').querySelectorAll('input').forEach((el,i)=>el.value=jobs[i].seconds);render()};
$('#analyse').onclick=()=>{try{load($('#yaml').value,null,'User YAML · assumed 60s per job until edited')}catch(e){showError(e)}};
$('#yaml').oninput=()=>{$('#status').textContent='YAML changed. Press Draw this workflow to replace the current result.'};
for(const id of ['shards','cache','saving','overhead'])$('#'+id).oninput=render;
$('#durations').oninput=e=>{const i=e.target.dataset.duration;if(i!==undefined){jobs[+i].seconds=e.target.value===''?NaN:+e.target.value;jobs[+i].measured=false;e.target.previousElementSibling.textContent='user estimate';$('#status').textContent=currentSource+' · timings edited as estimates';render()}};
$('#fetch').onsubmit=async e=>{e.preventDefault();if(loading)return;if(Date.now()-loadedAt<30000){showError(new Error('Wait 30 seconds between public fetches, or use a cached recording.'));return}loading=true;showError(null);loadedAt=Date.now();$('#fetch-button').disabled=true;$('#fetch-button').textContent='Fetching…';try{const rec=await fetchRun($('#repo').value);load(rec.yaml,rec,`Just fetched public run · ${rec.repo} · ${rec.name}`)}catch(e){showError(e)}finally{loading=false;$('#fetch-button').disabled=false;$('#fetch-button').textContent='Fetch'}};
const first=snapshots.reduce((a,b)=>Object.keys(parseWorkflow(b.yaml,b)).length>Object.keys(parseWorkflow(a.yaml,a)).length?b:a,snapshots[0]);
load(first.yaml,first,`Cached public recording · ${first.repo} · ${first.name}`);
