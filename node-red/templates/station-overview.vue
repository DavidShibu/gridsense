<template>
  <section class="gs-overview">
    <header class="gs-hero">
      <div><p class="gs-eyebrow">GRIDSENSE / ENERGY OPERATIONS</p>
        <h1>Station overview</h1><p>Every vehicle. Every kilowatt. One clear view.</p>
      </div>
      <div class="gs-hero-status">
        <span :class="['gs-pill', fresh ? 'good' : 'waiting']"><span aria-hidden="true">●</span> {{ !state ? 'Awaiting telemetry' : fresh ? 'Telemetry live' : 'Telemetry stale' }}</span>
        <span>Last sensor update · {{ lastSeen }}</span>
        <span v-if="state">Simulation · {{ simTime(state.hour) }}</span>
      </div>
    </header>

    <div v-if="!state" class="gs-empty" role="status"><h3>Ready when your station is</h3><p>Start the simulator to see charging sessions, grid load and electricity prices here.</p></div>
    <template v-else>
      <div v-if="!fresh" class="gs-stale" role="status">Live updates have paused. Values below are the last received readings and may no longer reflect the station.</div>
      <div class="gs-kpis">
        <article class="gs-kpi gs-load-card"><p class="gs-label">Grid load</p>
          <svg class="gs-load-gauge" viewBox="0 0 168 168" role="img" :aria-label="'Grid load: '+gauge.value+' kilowatts. '+gauge.label+'. Scale 0 to 10 kilowatts.'">
            <circle cx="84" cy="84" r="74" fill="none" stroke="#16a34a" stroke-width="3" pathLength="100" stroke-dasharray="70 100" transform="rotate(-90 84 84)" />
            <circle cx="84" cy="84" r="74" fill="none" stroke="#eab308" stroke-width="3" pathLength="100" stroke-dasharray="25 100" stroke-dashoffset="-70" transform="rotate(-90 84 84)" />
            <circle cx="84" cy="84" r="74" fill="none" stroke="#dc2626" stroke-width="3" pathLength="100" stroke-dasharray="5 100" stroke-dashoffset="-95" transform="rotate(-90 84 84)" />
            <circle cx="84" cy="84" r="60" fill="none" stroke="#e7eeeb" stroke-width="12" />
            <circle v-if="gauge.percent>0" class="gs-gauge-value" cx="84" cy="84" r="60" fill="none" :stroke="gauge.color" stroke-width="12" pathLength="100" :stroke-dasharray="gauge.percent+' 100'" transform="rotate(-90 84 84)" />
            <text x="84" y="82" text-anchor="middle" class="gs-gauge-number" :fill="gauge.color">{{ gauge.value }}</text>
            <text x="84" y="104" text-anchor="middle" class="gs-gauge-unit">kW / 10 kW</text>
          </svg>
          <p class="gs-gauge-status" :style="{color:gauge.color}">{{ gauge.label }}</p>
          <p class="gs-gauge-legend"><span>🟢 &lt;7</span><span>🟡 7–9.5</span><span>🔴 &gt;9.5</span></p>
          <p class="gs-muted">{{ fmt(state.operating_limit_kw,1) }} kW operating limit <span v-if="overLimit" class="gs-danger">· Above limit</span></p>
        </article>
        <article class="gs-kpi"><p class="gs-label">Charging now</p><div class="gs-value">{{ charging }} <small>/ {{ state.chargers?.length || 0 }} ports</small></div>
          <p class="gs-muted">{{ queued }} waiting · {{ completed }} complete</p></article>
        <article class="gs-kpi"><p class="gs-label">Current tariff</p><div class="gs-value">{{ fmt(state.price_per_kwh,0) }} <small>INR/kWh</small></div>
          <p class="gs-muted">{{ tariffLabel }} · simulated pricing</p></article>
        <article class="gs-kpi"><p class="gs-label">Next departure</p><div class="gs-value gs-value-time">{{ nextDeparture ? simTime(nextDeparture.departure) : '—' }}</div>
          <p class="gs-muted">{{ nextDeparture ? nextDeparture.id + ' · ' + fmt(nextDeparture.remaining_kwh) + ' kWh remaining' : 'No upcoming departures' }}</p></article>
      </div>

      <div class="gs-section-heading"><div><p class="gs-eyebrow">LIVE SESSIONS</p><h2>Your charging fleet</h2></div>
        <label class="gs-search"><span class="gs-sr-only">Search vehicle ID</span><input v-model="search" type="search" placeholder="Search vehicle ID…" /></label>
      </div>
      <div class="gs-filter-row" aria-label="Filter charging sessions">
        <button v-for="item in filters" :key="item.key" type="button" :aria-pressed="filter===item.key" :class="{'is-active':filter===item.key}" @click="filter=item.key">{{ item.label }}</button>
        <span class="gs-muted">{{ visibleVehicles.length }} of {{ vehicles.length }} vehicles</span>
      </div>
      <div class="gs-fleet-head" aria-hidden="true"><span>Vehicle / status</span><span>Battery / target</span><span>Charging power</span><span>Departure</span><span>Energy needed</span></div>
      <div v-for="ev in visibleVehicles" :key="ev.id" class="gs-fleet-row">
        <div class="gs-vehicle"><span class="gs-vehicle-icon" aria-hidden="true">↯</span><div><strong>{{ ev.id }}</strong><span :class="['gs-status', ev.status]">{{ statusLabel(ev.status) }}</span></div></div>
        <div><span class="gs-mobile-label">Battery / target</span><strong>{{ fmt(ev.soc*100,0) }}%</strong><span class="gs-muted"> / {{ fmt(ev.target*100,0) }}%</span><div class="gs-battery"><span :style="{width:Math.max(0,Math.min(100,ev.soc*100))+'%'}"></span><i :style="{left:Math.max(0,Math.min(100,ev.target*100))+'%'}" title="Target state of charge"></i></div></div>
        <div><span class="gs-mobile-label">Charging power</span><strong>{{ fmt(ev.power_kw) }} kW</strong><small class="gs-muted gs-block">{{ ev.charger || 'No port assigned' }}</small></div>
        <div><span class="gs-mobile-label">Departure</span><strong>{{ simTime(ev.departure) }}</strong><small class="gs-muted gs-block">Simulation time</small></div>
        <div><span class="gs-mobile-label">Energy needed</span><strong>{{ fmt(ev.remaining_kwh) }} kWh</strong></div>
      </div>
      <div v-if="!visibleVehicles.length" class="gs-empty"><h3>No matching vehicles</h3><p>Try another vehicle ID or select All sessions.</p><button type="button" class="gs-reset" @click="filter='all';search=''">Clear filters</button></div>
      <p class="gs-footnote">Synthetic station data · {{ state.capacity_kw }} kW physical rating · 5% capacity reserve</p>
    </template>
  </section>
</template>
<script>
export default {
  data() { return {now:Date.now(),timer:null,search:'',filter:'all',filters:[{key:'all',label:'All sessions'},{key:'active',label:'On site'},{key:'queued',label:'Waiting'},{key:'complete',label:'Complete'},{key:'departed',label:'Departed'}]} },
  mounted() { this.timer=setInterval(()=>{this.now=Date.now()},1000) },
  unmounted() { clearInterval(this.timer) },
  computed: {
    state() { const p=this.msg?.payload; return Array.isArray(p?.vehicles) ? p : null },
    vehicles() { return this.state?.vehicles || [] },
    fresh() { const age=this.now-(this.state?.timestamp || 0)*1000; return !!this.state && age>=-5000 && age<10000 },
    lastSeen() { return Number.isFinite(this.state?.timestamp) ? new Date(this.state.timestamp*1000).toLocaleTimeString() : 'Not received' },
    charging() { return this.vehicles.filter(e=>e.status==='charging').length },
    queued() { return this.vehicles.filter(e=>e.status==='queued').length },
    completed() { return this.vehicles.filter(e=>e.status==='complete').length },
    gauge() {
      const kw=this.state?.load_kw;
      if(!Number.isFinite(kw) || kw<0) return {value:'—',percent:0,color:'#64748b',label:'Reading unavailable'};
      return {value:kw.toFixed(2),percent:Math.min(100,kw*10),
        color:kw<7?'#16a34a':kw<=9.5?'#eab308':'#dc2626',
        label:kw<7?'Normal load':kw<=9.5?'High load':kw<10?'Above operating limit':'At or above rated capacity'};
    },
    overLimit() { return this.state?.load_kw > this.state?.operating_limit_kw+1e-6 },
    tariffLabel() { const p=this.state?.price_per_kwh; return !Number.isFinite(p)?'Tariff unavailable':p<=3?'Off-peak rate':p>=12?'Peak rate':'Standard rate' },
    nextDeparture() { return this.vehicles.filter(e=>e.departure>this.state.hour && e.arrival<=this.state.hour && e.remaining_kwh>.01).sort((a,b)=>a.departure-b.departure)[0] },
    visibleVehicles() { return this.vehicles.filter(e=>e.id.toLowerCase().includes(this.search.toLowerCase()) && (this.filter==='all' || (this.filter==='active' ? e.arrival<=this.state.hour && this.state.hour<e.departure : e.status===this.filter))) }
  },
  methods: {
    fmt(value,digits=2) { return Number.isFinite(value)?value.toFixed(digits):'—' },
    simTime(hour) { if(!Number.isFinite(hour)) return '—'; const minutes=Math.floor(hour*60+1e-6); const day=Math.floor(minutes/1440); return (day?'Day '+(day+1)+' · ':'')+String(Math.floor(minutes/60)%24).padStart(2,'0')+':'+String(minutes%60).padStart(2,'0') },
    statusLabel(status) { return {scheduled:'Scheduled',queued:'Waiting',charging:'Charging',connected:'Connected',complete:'Target reached',departed:'Departed'}[status] || status }
  }
}
</script>
<style>
.gs-page { color:#172b3a; font-family:Inter,'Segoe UI',sans-serif; }
.gs-overview { padding:4px; }
.gs-hero { display:flex;align-items:center;justify-content:space-between;gap:24px;padding:32px;border-radius:16px;background:linear-gradient(115deg,#102d35,#164f4b);color:#fff;margin-bottom:24px; }
.gs-hero h1 { font-size:clamp(26px,4vw,36px);font-weight:650;letter-spacing:-1px;margin:8px 0;line-height:1.2; }
.gs-hero p { color:#c5dedb;margin-bottom:0; }
.gs-eyebrow { font-size:11px;font-weight:700;letter-spacing:1.8px;color:#55736d;margin:0 0 6px; }
.gs-hero .gs-eyebrow { color:#99d9c6; }
.gs-hero-status { display:flex;flex-direction:column;align-items:flex-end;gap:10px;font-size:12px;color:#c5dedb;white-space:nowrap; }
.gs-pill { border-radius:100px;padding:7px 12px;font-size:12px;font-weight:650;display:inline-flex;gap:7px;align-items:center; }
.gs-pill.good { background:#d1fae5;color:#065f46; }.gs-pill.waiting { background:#fef3c7;color:#854d0e; }
.gs-kpis { display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:20px 0 32px; }
.gs-kpi { padding:22px;background:#fff;border:1px solid #dce7e4;border-radius:14px;box-shadow:0 4px 16px #173c3205; }
.gs-load-card { text-align:center; }.gs-load-card>.gs-label { text-align:left; }
.gs-load-gauge { display:block;width:100%;max-width:168px;height:auto;margin:0 auto; }
.gs-gauge-number { font:650 28px 'Segoe UI',sans-serif;letter-spacing:-1px; }.gs-gauge-unit { font:11px 'Segoe UI',sans-serif;fill:#607571; }
.gs-gauge-status { font-size:12px;font-weight:650;margin:6px 0 8px; }
.gs-gauge-legend { display:flex;justify-content:center;flex-wrap:wrap;gap:8px;font-size:10px;color:#526b68;margin:8px 0 12px; }
.gs-label { color:#526b68;font-size:12px;font-weight:600;margin:0 0 12px; }
.gs-value { font-size:32px;font-weight:650;letter-spacing:-1px;color:#123b35;line-height:1.3;margin-bottom:12px; }
.gs-value small { font-size:12px;font-weight:500;letter-spacing:0;color:#526b68; }.gs-value-time { font-size:26px; }
.gs-muted { color:#607571;font-size:12px; }.gs-kpi p:last-child { margin-bottom:0; }
.gs-meter,.gs-battery { height:6px;border-radius:8px;background:#e7eeeb;position:relative;margin:12px 0; }
.gs-meter span,.gs-battery span { display:block;height:100%;border-radius:8px;transition:width .35s;background:#10b981; }
.gs-battery { max-width:140px;margin:8px 0 0; }.gs-battery i { position:absolute;top:-3px;height:12px;width:2px;background:#344b46; }
.gs-section-heading { display:flex;align-items:center;justify-content:space-between;gap:16px;margin:20px 0; }
.gs-section-heading h2 { font-size:22px;font-weight:650;letter-spacing:-.5px;margin:0; }
.gs-search input { padding:10px 14px;border:1px solid #cddbd6;border-radius:10px;background:#fff;max-width:100%;font-size:13px;min-height:44px; }
.gs-filter-row { display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:18px; }.gs-filter-row button,.gs-reset { padding:9px 13px;border:1px solid #dae5e0;border-radius:8px;color:#46615a;background:#fff;font-size:12px;font-weight:600;min-height:40px;cursor:pointer; }
.gs-filter-row .is-active { background:#e0f2e9;border-color:#a0cdb7;color:#176345; }.gs-filter-row>.gs-muted { margin-left:auto; }
.gs-page button:focus-visible,.gs-page input:focus-visible,.gs-page select:focus-visible,.gs-page summary:focus-visible { outline:3px solid #26826b;outline-offset:3px; }
.gs-fleet-head,.gs-fleet-row { display:grid;grid-template-columns:1.3fr 1.1fr 1fr 1fr 1fr;gap:16px;align-items:center;padding:16px; }
.gs-fleet-head { background:#f4f8f6;border-radius:8px;color:#58736b;font-size:11px;font-weight:600; }
.gs-fleet-row { border-bottom:1px solid #e8efeb;min-height:88px;font-size:13px; }.gs-fleet-row:hover { background:#f8fbf9; }
.gs-vehicle { display:flex;align-items:center;gap:12px; }.gs-vehicle-icon { display:grid;place-items:center;width:36px;height:40px;background:#e7f3ed;border-radius:10px;font-size:25px;color:#21765a; }
.gs-status { display:block;font-size:11px;margin-top:3px;color:#607571; }.gs-status.charging,.gs-status.complete { color:#16734d; }.gs-status.queued { color:#93620c; }
.gs-block { display:block;margin-top:4px; }.gs-mobile-label { display:none; }.gs-danger { color:#b91c1c; }
.gs-footnote { font-size:11px;color:#71837d;margin:18px 0 4px; }.gs-stale { border:1px solid #ebd299;border-radius:10px;padding:12px 16px;background:#fff8e7;color:#80570b;font-size:13px; }
.gs-empty { text-align:center;padding:48px 20px;color:#607571;background:#f7faf8;border:1px dashed #ccddd3;border-radius:12px; }.gs-empty h3 { color:#284c40;margin-bottom:8px; }.gs-empty p { margin-bottom:14px; }
.gs-sr-only { position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0; }
.gs-section { border:1px solid #dce7e4;box-shadow:0 4px 18px #173c3204; }
@media(max-width:1100px) { .gs-kpis { grid-template-columns:repeat(2,minmax(0,1fr)); }.gs-hero { padding:24px; } }
@media(max-width:650px) { .gs-hero { flex-direction:column;align-items:flex-start;gap:18px; }.gs-hero-status { align-items:flex-start; }.gs-kpis { gap:10px; }.gs-kpi { padding:16px; }.gs-value { font-size:26px; }.gs-value-time { font-size:20px; }.gs-section-heading { flex-direction:column;align-items:stretch; }.gs-search input { width:100%; }.gs-fleet-head { display:none; }.gs-fleet-row { grid-template-columns:1fr 1fr;border:1px solid #dce7e4;border-radius:12px;margin-bottom:12px;gap:18px; }.gs-vehicle { grid-column:1/-1; }.gs-mobile-label { display:block;font-size:10px;color:#607571;margin-bottom:4px; }.gs-filter-row>.gs-muted { width:100%;margin:0; }.gs-page { padding:0; } }
@media(prefers-reduced-motion:reduce) { .gs-meter span,.gs-battery span { transition:none; } }
</style>
