<template>
  <section class="gs-alerts" aria-live="polite">
    <div class="gs-section-heading"><div><p class="gs-eyebrow">REQUIRES YOUR ATTENTION</p><h2>Station health</h2></div><span v-if="msg?.payload?.decision" class="gs-muted">{{ msg.payload.decision.alerts?.length || 0 }} active alerts</span></div>
    <p v-if="!msg?.payload?.decision">Waiting for analytics...</p>
    <template v-else>
      <div v-if="stale" class="gs-alert warning">Warning: analytics is stale. Last decisions are shown below.</div>
      <div v-for="(alert, i) in alerts" :key="i" :class="['gs-alert', alert.level]">
        <strong>{{ alert.level.toUpperCase() }}</strong> — {{ alert.text }}
      </div>
      <p class="gs-muted">{{ policyLabel }}</p>
    </template>
  </section>
</template>
<script>
export default {
  data() { return { now: Date.now(), timer: null } },
  mounted() { this.timer = setInterval(() => { this.now = Date.now() }, 1000) },
  unmounted() { clearInterval(this.timer) },
  computed: {
    policyLabel() { return {optimal:'Price optimization active · deadline constraints satisfied by the plan',feasible_time_limit:'Feasible price plan · optimization time limit reached',idle:'No charging demand to schedule',fallback_edf:'Deadline priority active · price optimization unavailable',disabled:'Price optimization is turned off'}[this.msg?.payload?.decision?.tou_status] || 'Waiting for scheduling status' },
    stale() { return this.now - (this.msg?.payload?.decision?.sensor_timestamp || 0) * 1000 > 10000 },
    alerts() {
      const values = this.msg?.payload?.decision?.alerts || [];
      return values.length ? values.map(text => ({ text,
        level: /cannot meet|unmet|exceeded|violation/i.test(text) ? 'critical' : 'warning'
      })) : this.stale ? [] : [{ level: 'success', text: 'No current scheduling alerts. Charging is being managed automatically.' }];
    }
  }
}
</script>
<style>
.gs-alerts { padding: 16px; }
.gs-alert { padding: 12px 16px; margin: 8px 0; border-radius: 8px; border-left: 5px solid; }
.gs-alert.critical { background: #fee2e2; color: #991b1b; border-color: #dc2626; }
.gs-alert.warning { background: #fef3c7; color: #854d0e; border-color: #d97706; }
.gs-alert.success { background: #dcfce7; color: #166534; border-color: #16a34a; }
</style>
