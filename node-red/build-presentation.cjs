const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname,'..');
const report = JSON.parse(fs.readFileSync(path.join(root,'artifacts/ml_comparison.json'),'utf8'));
const ppt = new pptxgen();
ppt.layout='LAYOUT_WIDE'; ppt.author='GridSense Team 3';
ppt.title='GridSense — updated IoT and ML rubric';
const modelResults=Object.entries(report.models).map(([n,m])=>`${n}: RMSE ${m.test.rmse_kwh.toFixed(2)} kWh; F1 ${m.test.f1.toFixed(3)}`).join('\n');
const slides=[
 ['GridSense', 'Team 3: Smart EV Charging and Load Management\nUpdated architecture, three ML paradigms and performance evaluation'],
 ['Architecture: independent paths','Python sensor simulation → MQTT ev/telemetry → Node-RED\nPath A: direct live Node-RED Dashboard\nPath B: SQLite commit → database read → ML/evaluation\nDecision → MQTT ev/actuator → simulated physical actuator\nAcknowledgement ev/ack → SQLite control metrics'],
 ['Sensor and actuator roles','Six EVs share two chargers and 10 kW site capacity.\n1 kW base load; staggered arrivals and fixed departures.\nSimulator publishes observations, not decisions.\nActuator shares the same plant state and applies validated plans.\nTargets, taper, command expiry and power limits are enforced.'],
 ['Three model paradigms','Traditional: DecisionTreeRegressor\nEnsemble: RandomForestRegressor (80 trees)\nDeep ANN: hidden layers 64 / 32 / 16, Adam backpropagation\nCalendar features → future-hour requested energy\nAll training rows come from SQLite, not runtime streams.'],
 ['Data and evaluation split','42 synthetic days: 1,008 hourly observations.\nHistory replay follows MQTT → Node-RED → SQLite.\n28 days train; 7 validate; 7 test.\nIdentical chronological split for all models.\nSelection uses validation RMSE and latency, never test scores.'],
 ['ML performance','Regression: RMSE, MAE and R² for hourly energy.\nClassification: high-demand alarm if energy ≥30 kWh.\nIndependent classifiers; balanced training; unchanged test data.\nThese scores answer different questions.\nSynthetic results do not establish real-world generalization.'],
 ['Measured model comparison',modelResults+'\nSelected on validation: '+report.selected_model+'\nFull metrics and warnings: artifacts/ml_comparison.json'],
 ['Computational performance','Training duration in seconds.\nMean/p95 single-row prediction latency after warm-up.\nPeak traced allocation bytes during fitting.\nSerialized model size in bytes.\nTracked allocations are not total process RSS/GPU memory.'],
 ['Decision and switching stability','Feasibility-aware EDF prioritizes actual departure deadlines.\nModels load and warm once before HTTP startup.\nSix-minute assignment dwell and stable socket mapping.\n0.25 kW deadband retained; no post-deadband redistribution.\nSafety, completion and departure override holds.'],
 ['Closed-loop results','Live test verified MQTT control and stored acknowledgements.\nPeak observed load: 9.5 kW (5% reserve).\nCongested run: 4/6 targets met; 65.5% energy fulfillment.\nFeasible low-energy run: all six targets met.\nBoth benchmarks: zero capacity violations and rapid switches.\nNo ML control-outcome improvement is established by these scenarios.'],
 ['Demonstration and viva','Start ./start.ps1; open /dashboard/station.\nTop panel is direct live data; lower panel is DB-backed evaluation.\nReplay history, train, inspect three-model comparison.\nStop analytics: live panel continues; actuator expires commands.\nChange capacity/deadline and explain feasibility.'],
 ['Limits and submission','Synthetic data; faculty approval remains external.\nHeuristic scheduling has no optimality guarantee.\nInstantaneous socket switching; simplified battery taper.\nSingle-host end-to-end timestamps; clock sync needed across hosts.\nReview README, REPORT_V5, metrics, flow and ZIP before submission.']
];
for(const [title,body] of slides){
 const s=ppt.addSlide(); s.background={color:'F1F5F9'};
 s.addText(title,{x:.6,y:.45,w:12.1,h:.8,fontSize:29,bold:true,color:'166534'});
 s.addText(body,{x:.7,y:1.6,w:11.9,h:4.9,fontSize:22,color:'0F172A',paraSpaceAfterPt:18});
 s.addText('GridSense · Team 3',{x:.7,y:7,w:11,h:.2,fontSize:10,color:'64748B'});
}
ppt.writeFile({fileName:path.join(root,'GridSense_Presentation.pptx')});
