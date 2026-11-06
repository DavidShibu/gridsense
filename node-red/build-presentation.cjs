const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');
const read = name => JSON.parse(fs.readFileSync(path.join(root, 'artifacts', name), 'utf8'));
const report = read('ml_comparison.json');
const live = read('live_check.json');
const tou = read('tou_comparison.json').results;
const ppt = new pptxgen();
ppt.layout = 'LAYOUT_WIDE';
ppt.author = 'GridSense Team 3';
ppt.title = 'GridSense - Distributed IoT EV Charging';
const modelResults = Object.entries(report.models).map(([name, m]) =>
  `${name}: RMSE ${m.test.rmse_kwh.toFixed(2)} kWh; F1 ${m.test.f1.toFixed(3)}`).join('\n');
const slides = [
  ['GridSense', 'Team 3: Smart EV Charging and Load Management\nTwo laptops, public cloud MQTT, Node-RED, SQLite and evaluated ML control'],
  ['Two-laptop architecture', 'Sensor laptop: Python sensor and actuator simulation\nTelemetry -> broker.emqx.io (TLS 8883) -> project Node-RED\nPath A: direct live dashboard\nPath B: SQLite commit -> database read -> ML -> decision\nCommands -> public broker -> sensor; acknowledgements -> project database'],
  ['Sensor and actuator', 'Six EVs; two charger sockets; 10 kW rated supply.\n1 kW base load; 9.5 kW total operating cap.\nReadings published every two seconds.\nActuator validates plans and applies them to simulated hardware.\nDuplicate, stale and unsafe commands are rejected.'],
  ['Five models, three categories', 'Traditional: decision tree and support vector models.\nEnsemble: random forest and XGBoost.\nNeural network: hidden layers 64 / 32 / 16.\nIndependent energy regressors and high-demand classifiers.\nAll training data is read from SQLite.'],
  ['Data and evaluation', '42 synthetic days: 1,008 hourly observations.\nHistory follows MQTT -> Node-RED -> SQLite.\n28 training days; 7 validation days; 7 test days.\nSelection uses validation RMSE and a 100 ms p95 latency limit.\nTest scores never select the model.'],
  ['Measured model comparison', modelResults + '\nSelected: ' + report.selected_model],
  ['Performance measurements', 'Regression: RMSE, MAE and R2.\nIndependent high-demand classification: accuracy, precision, recall, F1.\nTraining time, warmed inference latency and serialized size.\nPeak Python-tracked allocations, not total process/GPU memory.\nClosed loop: acknowledgements, response time, switches and safety.'],
  ['Decision and automation', 'Feasibility-aware deadline scheduling with a 5% supply reserve.\nTariff optimization shifts flexible demand to cheaper periods.\nSolver failure falls back to deadline scheduling.\nFallback policy uses dwell time, socket stability and a deadband.\nModels load once at startup; restart after retraining.'],
  ['Verified local MQTT loop', `${live.history_rows} history rows; ${live.stored_cycles} live cycles.\n${live.accepted_commands} accepted commands; ${live.stored_acknowledgements} stored acknowledgements.\nDashboard HTTP ${live.dashboard_http}; peak ${live.max_observed_load_kw} kW.\nMean response ${live.mean_response_ms.toFixed(2)} ms; p95 ${live.p95_response_ms.toFixed(2)} ms.\nLocal test; actual two-laptop network timing remains separate.`],
  ['Tariff demonstration', `Same EVs, energy requirements and deadlines.\nDelivered energy: ${tou.tou.delivered_kwh} kWh; all deadlines met.\nDeadline-only cost: INR ${tou.edf.charging_cost_inr}.\nTariff-aware cost: INR ${tou.tou.charging_cost_inr}.\nPeak site load: ${tou.edf.peak_grid_kw} kW vs ${tou.tou.peak_grid_kw} kW.\nSynthetic evening scenario; not a general savings guarantee.`],
  ['Demonstration commands', 'Project laptop: ./start.ps1 -PublicBroker\nSensor laptop: python simulator.py --public-broker\nDashboard: http://127.0.0.1:1880/dashboard/station\nCopy mqtt-public.json to both laptops; observe readings and acknowledgements.\nUse --tou-demo on the sensor for the evening scenario.'],
  ['Limits and reproduction', 'Synthetic readings, illustrative tariffs and simplified battery physics.\nCongested requests cannot all meet deadlines.\nML control-outcome improvement over baseline is not established.\nSynchronize laptop clocks for end-to-end latency measurements.\nPublic topics are not private; use synthetic data only (TLS enabled).\nSee README, GridSense_Final_Report.md and artifacts/*.json.']
];
for (const [title, body] of slides) {
  const slide = ppt.addSlide();
  slide.background = {color: 'F1F5F9'};
  slide.addText(title, {x: .6, y: .45, w: 12.1, h: .8, fontSize: 29, bold: true, color: '166534'});
  slide.addText(body, {x: .7, y: 1.6, w: 11.9, h: 4.9, fontSize: 21, color: '0F172A', paraSpaceAfterPt: 14, breakLine: false});
  slide.addText('GridSense - Team 3', {x: .7, y: 7, w: 11, h: .2, fontSize: 10, color: '64748B'});
}
ppt.writeFile({fileName: path.join(root, 'GridSense_Presentation.pptx')}).catch(error => { console.error(error); process.exitCode = 1; });
