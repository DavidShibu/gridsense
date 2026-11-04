<template>
  <section class="gs-price-chart" style="padding:16px">
    <div class="gs-section-heading"><div><p class="gs-eyebrow">TIME-OF-USE INSIGHTS</p><h2>Charge when energy costs less</h2></div>
      <label class="gs-chart-range">Show <select v-model.number="windowSize" aria-label="Price chart time window"><option :value="60">Last 2 simulated hours</option><option :value="180">Last 6 simulated hours</option><option :value="360">Last 12 simulated hours</option></select></label></div>
    <p class="gs-chart-legend"><span style="color:#166534">● Charging load (kW), left axis</span> ·
       <span style="color:#9a3412">● Price (INR/kWh), right axis</span></p>
    <svg v-if="points.length" viewBox="0 0 800 300" role="img" aria-label="Dual-axis line chart of charging load and electricity price over simulated time" style="width:100%;min-height:220px">
      <g v-for="tick in [0,1,2,3,4]" :key="tick">
        <line x1="65" x2="730" :y1="250-tick*50" :y2="250-tick*50" stroke="#e2e8f0"/>
        <text x="55" :y="255-tick*50" text-anchor="end" fill="#166534" font-size="13">{{ (loadMax*tick/4).toFixed(1) }}</text>
        <text x="740" :y="255-tick*50" fill="#9a3412" font-size="13">{{ (priceMax*tick/4).toFixed(1) }}</text>
      </g>
      <text x="65" y="25" fill="#166534">kW</text><text x="675" y="25" fill="#9a3412">INR/kWh</text>
      <polyline :points="line('load',loadMax)" fill="none" stroke="#166534" stroke-width="3"/>
      <polyline :points="line('price',priceMax)" fill="none" stroke="#c2410c" stroke-width="2"/>
      <text x="65" y="277" font-size="13">{{ points[0].hour.toFixed(2) }}</text>
      <text x="730" y="277" text-anchor="end" font-size="13">{{ points[points.length-1].hour.toFixed(2) }}</text>
      <text x="400" y="295" text-anchor="middle" font-size="13">Simulated hour (absolute, across midnight)</text>
    </svg>
    <p v-else>Waiting for telemetry with tariff fields...</p>
    <p v-if="latest" class="gs-chart-current"><span>Latest reading</span><strong>{{ latest.load.toFixed(2) }} kW</strong><strong>{{ latest.price.toFixed(2) }} INR/kWh</strong></p>
    <small class="gs-muted">{{ points.length }} samples shown · Charging load excludes base load · Simulated tariff</small>
  </section>
</template>
<script>
export default {
  data() { return {windowSize:180} },
  computed: {
    points() { const all=this.msg?.payload?.points || []; const end=all[all.length-1]?.hour; return all.filter(p=>p.hour>=end-this.windowSize/30) },
    latest() { return this.points[this.points.length-1] },
    loadMax() { return Math.max(1, ...this.points.map(p=>p.load)) * 1.1 },
    priceMax() { return Math.max(1, ...this.points.map(p=>p.price)) * 1.1 }
  },
  methods: {
    line(key, max) {
      const start=this.points[0].hour;
      const span=Math.max(1/30, this.points[this.points.length-1].hour-start);
      return this.points.map(p => `${65+665*(p.hour-start)/span},${250-200*p[key]/max}`).join(' ');
    }
  }
}
</script>
<style>
.gs-chart-range { display:flex;gap:8px;align-items:center;color:#607571;font-size:12px; }.gs-chart-range select { border:1px solid #cddbd6;border-radius:8px;background:#fff;color:#355e4e;padding:10px;min-height:44px; }
.gs-chart-legend { font-size:12px; }.gs-chart-current { display:flex;gap:18px;align-items:center;padding:14px 0;border-top:1px solid #e4ece7;font-size:13px; }.gs-chart-current span { color:#607571;font-size:11px; }.gs-chart-current strong { color:#184d3c; }
@media(max-width:650px) { .gs-chart-current { flex-wrap:wrap; }.gs-chart-legend { line-height:2; } }
</style>
