// script.js - merged, efficient, lag-minimised client-side analytics.
// - Separate live charts: typing (WPM/CPM), mouse (avg speed), scroll (px/s)
// - Heatmap (clicks) fixed and efficient
// - Initial baseline capture trigger & continuous verification via /verify
// - Per-sample throttling and bounded buffers
// Note: Requires Chart.js (loaded in pages)

(() => {
  // CONFIG
  const SAMPLE_THROTTLE_MS = 50; // mouse sampling throttle
  const CHART_UPDATE_MS = 400; // chart update cadence
  const POST_INTERVAL_MS = 3000; // server verification cadence
  const BASELINE_SECONDS = 10; // baseline capture duration when user triggers

  // BUFFERS & STATE
  let flights = [], dwells = [];
  let lastKeyTime = 0, lastKeyDown = {};
  let charTimestamps = [];

  let mouseSamples = [], mousePath = [], clickPositions = [], mouseClicks = 0;
  let lastMouseSample = 0, lastMouseMove = Date.now();

  let touchPath = [], touchSamples = [], touchMoves = 0, lastTouchTime = 0;

  let scrollSpeeds = [], scrollCount = 0, lastScrollY = window.scrollY || 0, lastScrollTime = Date.now();

  let idleMs = 0;
  let fraudScore = 0;

  // DOM helpers
  const $ = id => document.getElementById(id);

  // CHARTS
  function createChart(ctx, datasets, options={}) {
    if(!ctx) return null;
    return new Chart(ctx, {
      type: 'line',
      data: { labels: [], datasets },
      options: Object.assign({
        animation: { duration: 0 },
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#fff' } } },
        scales: { x: { ticks: { color: '#aaa' } }, y: { ticks: { color: '#aaa' } } }
      }, options)
    });
  }

  const typingChart = createChart($('typingChart')?.getContext('2d'), [
    { label: 'WPM', data: [], borderColor: '#ff9f1c', tension: 0.3 },
    { label: 'CPM', data: [], borderColor: '#ffd166', tension: 0.3 }
  ]);

  const mouseChart = createChart($('mouseChart')?.getContext('2d'), [
    { label: 'Mouse Avg Speed (px/s)', data: [], borderColor: '#27e0ff', tension: 0.3 }
  ]);

  const scrollChart = createChart($('scrollChart')?.getContext('2d'), [
    { label: 'Scroll Speed (px/s)', data: [], borderColor: '#7b61ff', tension: 0.3 }
  ]);

  function push(chart, values) {
    if(!chart) return;
    const MAX = 40;
    if(chart.data.labels.length >= MAX) {
      chart.data.labels.shift();
      chart.data.datasets.forEach(ds => ds.data.shift());
    }
    chart.data.labels.push('');
    if(Array.isArray(values)) {
      for(let i=0;i<chart.data.datasets.length;i++) chart.data.datasets[i].data.push(values[i] ?? null);
    } else {
      chart.data.datasets[0].data.push(values);
    }
    chart.update('none');
  }

  // HEATMAP
  const heatCanvas = $('mouseHeatmap');
  const heatCtx = heatCanvas ? (function setup(){ heatCanvas.width = Math.min(heatCanvas.clientWidth||300, 900); heatCanvas.height = 150; return heatCanvas.getContext('2d'); })() : null;
  function drawHeatmap() {
    if(!heatCtx) return;
    heatCtx.clearRect(0,0,heatCtx.canvas.width, heatCtx.canvas.height);
    const w = heatCtx.canvas.width, h = heatCtx.canvas.height;
    const buckets = {};
    clickPositions.slice(-1000).forEach(p => {
      const x = Math.floor((p.x / (window.innerWidth||1))*w), y = Math.floor((p.y/(window.innerHeight||1))*h);
      const key = `${x},${y}`; buckets[key] = (buckets[key]||0)+1;
    });
    const vals = Object.values(buckets); const max = vals.length ? Math.max(...vals) : 1;
    for(const k in buckets) {
      const [x,y] = k.split(',').map(Number);
      const intensity = buckets[k]/max;
      const r = 8 + intensity*18;
      const g = heatCtx.createRadialGradient(x,y,0,x,y,r);
      g.addColorStop(0, `rgba(255,0,120,${0.9*intensity})`); g.addColorStop(1, `rgba(255,0,120,0)`);
      heatCtx.fillStyle = g; heatCtx.beginPath(); heatCtx.arc(x,y,r,0,Math.PI*2); heatCtx.fill();
    }
  }

  // PATH METRICS
  function computePathMetrics(path) {
    if(!path||path.length<2) return { path_length:0, avg_speed:0, speed_var:0, direction_changes_per_sec:0, angular_entropy:0 };
    const dists=[], angles=[], times=[];
    for(let i=1;i<path.length;i++){
      const a=path[i-1], b=path[i]; const dx=b.x-a.x, dy=b.y-a.y; const dt=Math.max(1,b.t-a.t);
      dists.push(Math.hypot(dx,dy)); times.push(dt); angles.push(Math.atan2(dy,dx));
    }
    const total = dists.reduce((s,v)=>s+v,0);
    const speeds = dists.map((d,i)=>d/(times[i]/1000));
    const avg = speeds.length ? speeds.reduce((a,b)=>a+b,0)/speeds.length : 0;
    const varr = speeds.length ? speeds.map(s=>(s-avg)**2).reduce((a,b)=>a+b,0)/speeds.length : 0;
    let changes = 0; for(let i=1;i<angles.length;i++){ const da=Math.abs(angles[i]-angles[i-1]); const ang=Math.min(da,2*Math.PI-da); if(ang>Math.PI/6) changes++; }
    const durSec = (path[path.length-1].t - path[0].t)/1000 || 1; const dirChanges = changes/durSec;
    const bins=12; const hist=new Array(bins).fill(0);
    for(const a of angles){ const n=(a+Math.PI)/(2*Math.PI); let idx=Math.floor(n*bins); if(idx>=bins) idx=bins-1; hist[idx]++; }
    const tot = angles.length||1; let ent=0; for(let i=0;i<bins;i++){ const p=hist[i]/tot; if(p>0) ent-=p*Math.log2(p); }
    return { path_length:Math.round(total), avg_speed:Math.round(avg), speed_var:Math.round(varr), direction_changes_per_sec:+dirChanges.toFixed(2), angular_entropy:+ent.toFixed(2) };
  }

  // TYPING HANDLERS
  const typingEl = $('typing');
  typingEl?.addEventListener('keydown', e => {
    const now = Date.now();
    if(lastKeyTime) { flights.push(now - lastKeyTime); if(flights.length>2000) flights.shift(); push($('chart')?.getContext?null:null); } // no-op to keep logic
    lastKeyTime = now;
    lastKeyDown[e.code||e.key] = now;
  });
  typingEl?.addEventListener('keyup', e=>{
    const now = Date.now();
    const down = lastKeyDown[e.code||e.key]; if(down){ dwells.push(now-down); if(dwells.length>2000) dwells.shift(); }
    delete lastKeyDown[e.code||e.key];
    // record char event for WPM/CPM
    charTimestamps.push(now); if(charTimestamps.length>2000) charTimestamps.shift();
    updateTypingStats();
  });
  typingEl?.addEventListener('input', e=>{
    // mobile input fallback - assume at least one char per input
    const now = Date.now(); charTimestamps.push(now); if(charTimestamps.length>2000) charTimestamps.shift();
    const avgFlight = Math.round((flights.reduce((a,b)=>a+b,0)/Math.max(1,flights.length))||0);
    $('flight') && ($('flight').innerText = avgFlight + ' ms');
    updateTypingStats();
  });

  function updateTypingStats() {
    const now = Date.now(); const windowMs = 60000; const cutoff = now-windowMs;
    const recent = charTimestamps.filter(t=>t>=cutoff); const charCount = recent.length;
    const cpm = Math.round((charCount/(windowMs/60000))||0); const wpm = Math.round((charCount/5)/(windowMs/60000)||0);
    $('cpm') && ($('cpm').innerText = cpm + ' CPM'); $('wpm') && ($('wpm').innerText = wpm + ' WPM');
    if(typingChart) push(typingChart, [wpm,cpm]);
  }

  // MOUSE & TOUCH
  window.addEventListener('mousemove', e=>{
    const now = Date.now();
    if(now - lastMouseSample > SAMPLE_THROTTLE_MS){
      const sp = Math.abs(e.movementX||0)+Math.abs(e.movementY||0);
      mouseSamples.push(sp); if(mouseSamples.length>2000) mouseSamples.shift();
      mousePath.push({x:e.clientX,y:e.clientY,t:now}); if(mousePath.length>2000) mousePath.shift();
      lastMouseSample = now; lastMouseMove = now;
    }
  }, { passive:true });

  window.addEventListener('click', e=>{
    mouseClicks++; clickPositions.push({x:e.clientX,y:e.clientY,t:Date.now()}); if(clickPositions.length>2000) clickPositions.shift(); drawHeatmapSoon();
  }, { passive:true });

  window.addEventListener('touchmove', e=>{
    const now = Date.now();
    if(e.touches && e.touches[0]) {
      const t = e.touches[0]; touchPath.push({x:t.clientX,y:t.clientY,t:now}); if(touchPath.length>2000) touchPath.shift();
      touchMoves++; // simplistic
      // compute small sample
      const last = touchPath[touchPath.length-2];
      if(last){ const dx=t.clientX-last.x, dy=t.clientY-last.y, dt=Math.max(1, now-last.t); touchSamples.push((Math.hypot(dx,dy)/dt)*1000); if(touchSamples.length>2000) touchSamples.shift(); }
    }
    lastTouchTime = now;
  }, { passive:true });

  // SCROLL
  window.addEventListener('scroll', ()=>{
    const now = Date.now(); const y = window.scrollY || window.pageYOffset || 0;
    const dy = Math.abs(y - lastScrollY); const dt = Math.max(1, now - lastScrollTime);
    const sp = (dy/dt)*1000;
    scrollSpeeds.push(sp); if(scrollSpeeds.length>2000) scrollSpeeds.shift();
    lastScrollY = y; lastScrollTime = now;
    scrollCount++;
    const avgSc = Math.round(scrollSpeeds.reduce((a,b)=>a+b,0)/Math.max(1,scrollSpeeds.length));
    $('scrollSpeed') && ($('scrollSpeed').innerText = avgSc + ' px/s');
    if(scrollChart) push(scrollChart, avgSc);
    if(mouseChart) push(mouseChart, Math.round(mouseSamples.reduce((a,b)=>a+b,0)/Math.max(1,mouseSamples.length)));
  }, { passive:true });

  // heatmap draw debounce
  let heatTimer = null;
  function drawHeatmapSoon(){ if(heatTimer) return; heatTimer = setTimeout(()=>{ heatTimer=null; drawHeatmap(); }, 100); }

  // drawHeatmap uses clickPositions and heatCtx similar to earlier
  function drawHeatmap(){
    if(!heatCtx) return;
    heatCtx.clearRect(0,0,heatCtx.canvas.width,heatCtx.canvas.height);
    const w = heatCtx.canvas.width, h = heatCtx.canvas.height;
    const buckets = {}; clickPositions.slice(-1000).forEach(p => {
      const x = Math.floor((p.x/(window.innerWidth||1))*w), y = Math.floor((p.y/(window.innerHeight||1))*h);
      const key = `${x},${y}`; buckets[key]=(buckets[key]||0)+1;
    });
    const vals = Object.values(buckets); const max = vals.length ? Math.max(...vals) : 1;
    for(const k in buckets){ const [x,y]=k.split(',').map(Number); const intensity=buckets[k]/max; const r=8+intensity*18; const g = heatCtx.createRadialGradient(x,y,0,x,y,r); g.addColorStop(0, `rgba(255,0,120,${0.9*intensity})`); g.addColorStop(1, `rgba(255,0,120,0)`); heatCtx.fillStyle=g; heatCtx.beginPath(); heatCtx.arc(x,y,r,0,Math.PI*2); heatCtx.fill(); }
  }

  // periodic chart updates & UI refresh
  setInterval(()=>{
    const avgMouse = Math.round(mouseSamples.reduce((a,b)=>a+b,0)/Math.max(1,mouseSamples.length));
    $('mouseAvg') && ($('mouseAvg').innerText = avgMouse + ' px/s');
    $('clicks') && ($('clicks').innerText = mouseClicks);
    const avgScroll = Math.round(scrollSpeeds.reduce((a,b)=>a+b,0)/Math.max(1,scrollSpeeds.length));
    $('scrollSpeed') && ($('scrollSpeed').innerText = avgScroll + ' px/s');
    $('scrolls') && ($('scrolls').innerText = scrollCount);
    if(mouseChart) push(mouseChart, avgMouse);
    // ensure typing chart continuity
    updateTypingTick();
  }, CHART_UPDATE_MS);

  function updateTypingTick(){ updateTypingStats(); }

  function updateTypingStats(){
    const now = Date.now(); const windowMs = 60000; const cutoff = now-windowMs;
    const recent = charTimestamps.filter(t=>t>=cutoff); const cCount = recent.length;
    const cpm = Math.round((cCount/(windowMs/60000))||0), wpm = Math.round((cCount/5)/(windowMs/60000)||0);
    $('cpm') && ($('cpm').innerText = cpm + ' CPM'); $('wpm') && ($('wpm').innerText = wpm + ' WPM');
    if(typingChart) push(typingChart, [wpm,cpm]);
  }

  // initial baseline collection triggered by button
  $('startBaseline')?.addEventListener('click', async () => {
    $('baselineHint').innerText = 'Collecting baseline...';
    await collectBaseline(BASELINE_SECONDS);
    $('baselineHint').innerText = 'Baseline sent for analysis';
  });

  async function collectBaseline(seconds) {
    // gather samples locally for duration, then POST to /verify with initial=true
    const start = Date.now();
    const end = start + seconds*1000;
    const localFlights = [], localDwells=[], localMouse=[], localScroll=[], localClicks=[];
    // subscribe for the window
    function onKeydown(e){ const now=Date.now(); if(lastKeyTime) localFlights.push(now-lastKeyTime); lastKeyTime=now; lastKeyDown[e.code||e.key]=now; }
    function onKeyup(e){ const now=Date.now(); const d=lastKeyDown[e.code||e.key]; if(d){ localDwells.push(now-d); } delete lastKeyDown[e.code||e.key]; charTimestamps.push(now); }
    function onMouse(e){ const now=Date.now(); const sp=Math.abs(e.movementX||0)+Math.abs(e.movementY||0); localMouse.push(sp); }
    function onClick(e){ localClicks.push({x:e.clientX,y:e.clientY,t:Date.now()}); }
    function onScroll(e){ const now=Date.now(); const y=window.scrollY||window.pageYOffset||0; const dy=Math.abs(y-lastScrollY); const dt=Math.max(1, now-lastScrollTime); const sp=(dy/dt)*1000; localScroll.push(sp); lastScrollY=y; lastScrollTime=now; }

    window.addEventListener('keydown', onKeydown);
    window.addEventListener('keyup', onKeyup);
    window.addEventListener('mousemove', onMouse);
    window.addEventListener('click', onClick);
    window.addEventListener('scroll', onScroll);

    // await end
    await new Promise(r => setTimeout(r, seconds*1000));

    window.removeEventListener('keydown', onKeydown);
    window.removeEventListener('keyup', onKeyup);
    window.removeEventListener('mousemove', onMouse);
    window.removeEventListener('click', onClick);
    window.removeEventListener('scroll', onScroll);

    // prepare payload
    const payload = {
      username: sessionStorage.getItem('authguard_user') || 'default_user',
      flight: localFlights,
      dwell: localDwells,
      mouse_speed: localMouse.length ? Math.round(localMouse.reduce((a,b)=>a+b,0)/localMouse.length) : 0,
      click_positions: localClicks,
      scroll_speeds: localScroll,
      scroll_speed: localScroll.length ? Math.round(localScroll.reduce((a,b)=>a+b,0)/localScroll.length) : 0,
      initial: true,
      ts: Date.now()
    };

    try {
      const res = await fetch('http://127.0.0.1:5000/verify', {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
      });
      const data = await res.json();
      // display analysis result
      $('analysisArea') && ($('analysisArea').innerHTML = `<b>Baseline analysis:</b> ${data.status} - fraud_score ${data.fraud_score}%`);
      $('statFraud') && ($('statFraud').innerText = data.fraud_score + '%');
      $('statStatus') && ($('statStatus').innerText = data.status);
    } catch (err) {
      console.error('Baseline send failed', err);
      $('analysisArea') && ($('analysisArea').innerText = 'Baseline analysis failed (network).');
    }
  }

  // periodic verification send (continuous)
  setInterval(async ()=>{
    // only if we have some data
    if(!flights.length && !charTimestamps.length) return;
    if(!mouseSamples.length && !touchSamples.length && !scrollSpeeds.length) return;

    const fAvg = Math.round(flights.reduce((a,b)=>a+b,0)/Math.max(1,flights.length) || 0);
    const dAvg = Math.round(dwells.reduce((a,b)=>a+b,0)/Math.max(1,dwells.length) || 0);
    const mAvg = Math.round(mouseSamples.reduce((a,b)=>a+b,0)/Math.max(1,mouseSamples.length) || 0);
    const tAvg = Math.round(touchSamples.reduce((a,b)=>a+b,0)/Math.max(1,touchSamples.length) || 0);
    const scAvg = Math.round(scrollSpeeds.reduce((a,b)=>a+b,0)/Math.max(1,scrollSpeeds.length) || 0);

    const mouse_metrics = computePathMetrics(mousePath.slice(-500));
    const touch_metrics = computePathMetrics(touchPath.slice(-500));

    const payload = {
      username: sessionStorage.getItem('authguard_user') || 'default_user',
      flight: flights.slice(-500), dwell: dwells.slice(-500),
      chars_timestamps: charTimestamps.slice(-1000),
      mouse_speed: mAvg, mouse_var: 0,
      mouse_path: mousePath.slice(-500), mouse_metrics,
      touch_speed: tAvg, touch_path: touchPath.slice(-500), touch_metrics,
      click_positions: clickPositions.slice(-500), clicks: mouseClicks,
      scrolls: scrollCount, scroll_speeds: scrollSpeeds.slice(-500), scroll_speed: scAvg,
      idle_ms: idleMs, fraud_score: fraudScore,
      ts: Date.now()
    };
    try {
      const r = await fetch('http://127.0.0.1:5000/verify', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      if(r.ok){
        const data = await r.json();
        $('statFraud') && ($('statFraud').innerText = data.fraud_score + '%');
        $('statStatus') && ($('statStatus').innerText = data.status);
        // optionally update analysis area
        $('analysisArea') && ($('analysisArea').innerHTML = `<b>Live:</b> ${data.status} · fraud ${data.fraud_score}% · confidence ${data.confidence||0}%`);
      }
    } catch (err) { console.warn('verify error', err); }
  }, POST_INTERVAL_MS);

  // helper computePathMetrics inlined above (reused)
  function computePathMetrics(path){
    if(!path||path.length<2) return { path_length:0, avg_speed:0, speed_var:0, direction_changes_per_sec:0, angular_entropy:0 };
    const dists=[], angles=[], times=[];
    for(let i=1;i<path.length;i++){ const a=path[i-1], b=path[i]; const dx=b.x-a.x, dy=b.y-a.y, dt=Math.max(1,b.t-a.t); dists.push(Math.hypot(dx,dy)); times.push(dt); angles.push(Math.atan2(dy,dx)); }
    const total=dists.reduce((s,v)=>s+v,0); const speeds=dists.map((d,i)=>d/(times[i]/1000)); const avg = speeds.length ? speeds.reduce((a,b)=>a+b,0)/speeds.length : 0;
    const varr = speeds.length ? speeds.map(s=>(s-avg)**2).reduce((a,b)=>a+b,0)/speeds.length : 0; let changes=0;
    for(let i=1;i<angles.length;i++){ const da=Math.abs(angles[i]-angles[i-1]); const ang=Math.min(da,2*Math.PI-da); if(ang>Math.PI/6) changes++; }
    const dur=(path[path.length-1].t - path[0].t)/1000 || 1; const dirChanges = changes/dur;
    const bins=12, hist=new Array(bins).fill(0);
    for(const a of angles){ const n=(a+Math.PI)/(2*Math.PI); let idx=Math.floor(n*bins); if(idx>=bins) idx=bins-1; hist[idx]++; }
    const tot = angles.length||1; let ent=0; for(let i=0;i<bins;i++){ const p=hist[i]/tot; if(p>0) ent-=p*Math.log2(p); }
    return { path_length:Math.round(total), avg_speed:Math.round(avg), speed_var:Math.round(varr), direction_changes_per_sec:+dirChanges.toFixed(2), angular_entropy:+ent.toFixed(2) };
  }

  // expose some debug
  window.AuthGuard = { computePathMetrics };
})();