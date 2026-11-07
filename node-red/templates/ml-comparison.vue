<template>
  <section class="gs-ml" v-if="msg?.payload?.decision">
    <div class="gs-section-heading"><div><p class="gs-eyebrow">PREDICTION & PERFORMANCE</p><h2>Intelligence behind each decision</h2></div><span class="gs-pill good">{{ Object.keys(msg.payload.decision.performance.models).length }} models evaluated</span></div>
    <p>Training data: {{ msg.payload.decision.performance.data_source || 'unreported legacy source' }}</p>
    <div class="gs-model-summary">
      <div><span>Selected model</span><strong>{{ modelName(msg.payload.decision.model) }}</strong></div>
      <div><span>Next-hour energy forecast</span><strong>{{ forecast }}</strong></div>
      <div><span>Prediction time</span><strong>{{ fmt(msg.payload.decision.inference_ms, 3) }} <small>ms</small></strong></div>
    </div>
    <div style="overflow-x:auto">
      <table>
        <thead><tr><th>Model</th><th>Accuracy</th><th>RMSE (kWh)</th><th>MAE (kWh)</th><th>R²</th><th>p95 inference (ms)</th></tr></thead>
        <tbody><tr v-for="(m, name) in msg.payload.decision.performance.models" :key="name"
          :class="{selected: name === msg.payload.decision.model}">
          <td><strong>{{ modelName(name) }}</strong> <span v-if="name === msg.payload.decision.model" class="gs-model-winner">SELECTED</span></td>
          <td>{{ fmt(m.test.accuracy * 100, 1) }}%</td><td>{{ fmt(m.test.rmse_kwh) }}</td>
          <td>{{ fmt(m.test.mae_kwh) }}</td><td>{{ fmt(m.test.r2, 3) }}</td>
          <td>{{ fmt(m.computational.inference_p95_ms, 3) }}</td>
        </tr></tbody>
      </table>
    </div>
    <p v-if="!Object.keys(msg.payload.decision.performance.models).length">Train models to populate this table.</p>
    <p class="gs-ml-note">Selected by validation error, with a 100 ms p95 latency limit. Lower RMSE and MAE are better; higher R² and accuracy are better.</p>
    <details><summary>How to read these metrics</summary><p>Accuracy measures the companion high-demand classifier (energy ≥30 kWh). RMSE, MAE and R² measure the energy regressor. Test scores use held-out days from {{ msg.payload.decision.performance.data_source || 'unreported legacy source' }}. The selected model must beat the constant baseline on validation RMSE.</p></details>
    <details><summary>Closed-loop performance</summary>
      <div class="gs-control-grid"><div v-for="(value, key) in msg.payload.closed_loop" :key="key"><span>{{ metricName(key) }}</span><strong>{{ value === null ? 'Not yet measurable' : typeof value==='number' ? fmt(value,Number.isInteger(value)?0:3) : value }}</strong></div></div>
    </details>
    <details><summary>Current charging assignments</summary>
      <p v-for="a in msg.payload.decision.assignments" :key="a.charger_id">{{ a.charger_id }} → {{ a.ev_id }}: {{ fmt(a.rate_kw) }} kW</p>
    </details>
  </section><p v-else>Waiting for stored-data analytics...</p>
</template>
<script>
export default {
  methods: {
    fmt(v, digits=2) { return Number.isFinite(v) ? v.toFixed(digits) : '—' },
    modelName(name) { return {traditional_decision_tree:'Decision Tree',ensemble_random_forest:'Random Forest',deep_ann:'Neural Network',traditional_svr:'Support Vector',ensemble_xgboost:'XGBoost',constant_baseline:'Constant baseline',untrained_safe_rules:'Deadline rules (untrained)'}[name] || name },
    metricName(key) { const value=key.replace(/_/g,' ').replace(/\bkw\b/g,'kW').replace(/\bkwh\b/g,'kWh'); return value.charAt(0).toUpperCase()+value.slice(1) }
  },
  computed: { forecast() {
    const d = this.msg?.payload?.decision;
    return d?.model === 'untrained_safe_rules' ? 'Unavailable (untrained)' : this.fmt(d?.forecast_next_hour_kwh) + ' kWh';
  } }
}
</script>
<style>
.gs-ml { padding: 16px; }
.gs-ml table { width:100%; border-collapse:collapse; text-align:left; }
.gs-ml th, .gs-ml td { padding:12px; border-bottom:1px solid #e2e8f0; white-space:nowrap; }
.gs-ml th { background:#f3f7f5;color:#526b63;font-size:11px; }
.gs-ml .selected { background:#dcfce7; color:#166534; }
.gs-ml td { font-size:13px; }
.gs-model-summary { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:24px 0; }
.gs-model-summary>div { background:#f4f8f6;border:1px solid #e0eae4;padding:18px;border-radius:12px; }
.gs-model-summary span,.gs-control-grid span { display:block;font-size:11px;color:#607571;margin-bottom:8px; }
.gs-model-summary strong { font-size:18px;color:#184d3c; }.gs-model-summary small { font-size:12px; }
.gs-model-winner { display:inline-block;font-size:9px;font-weight:700;letter-spacing:.8px;background:#bce8ca;color:#155c32;padding:4px 7px;border-radius:5px;margin-left:8px; }
.gs-ml-note { color:#607571;font-size:12px;margin:16px 0; }
.gs-ml details { border-top:1px solid #e4ece7;padding:16px 0;font-size:13px; }.gs-ml summary { cursor:pointer;font-weight:600;color:#355e4e; }.gs-ml details p { margin:12px 0 0;color:#607571; }
.gs-control-grid { display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:20px;margin-top:20px; }
@media(max-width:650px) { .gs-model-summary { grid-template-columns:1fr;gap:8px; }.gs-ml { padding:8px; }.gs-model-summary>div { padding:14px; } }
</style>
