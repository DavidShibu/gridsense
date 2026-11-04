"""Repeatable full-scenario closed-loop comparison (simulated, not network timing)."""
import json
import pickle
import time
from pathlib import Path
from station_core import Station, schedule
from decision_engine import stabilize
from ml_train import ARTIFACTS, predict


def evaluate(feasible=False):
    bundle=pickle.loads((ARTIFACTS/'bundle.pkl').read_bytes())
    results={}
    for name in ['constant_baseline',*bundle['report']['models']]:
        model=None if name=='constant_baseline' else pickle.loads((ARTIFACTS/f'{name}.pkl').read_bytes())
        current={**bundle,'model':model}
        station=Station()
        if feasible:
            for ev in station.vehicles:
                ev.target = min(ev.target, ev.soc+.05)
        previous=None
        switches=rapid=violations=0
        last_mapping={}
        last_switch={}
        peak=0
        latencies=[]
        for _ in range(185):
            state=station.snapshot()
            start=time.perf_counter()
            forecast,_=predict(current,state['hour'])
            profile=[bundle['baseline']]*24
            profile[int(state['hour']+1)%24]=forecast
            plan=stabilize(state,schedule(state,{'profile_kwh':profile}),previous)
            assert station.accept(plan)
            latencies.append((time.perf_counter()-start)*1000)
            mapping={a['charger_id']:a['ev_id'] for a in plan['assignments'] if a['rate_kw']>0}
            for charger in station.chargers:
                if last_mapping.get(charger)!=mapping.get(charger):
                    switches+=1
                    if charger in last_switch and station.hour-last_switch[charger]<.1-1e-8:
                        rapid+=1
                    last_switch[charger]=station.hour
            last_mapping=mapping
            previous=plan
            station.step(1/30)
            observed=station.snapshot()
            peak=max(peak,observed['load_kw'])
            violations+=int(observed['load_kw']>observed['capacity_kw']+1e-6)
        required=sum(e.delivered_kwh+e.remaining for e in station.vehicles)
        results[name]={'deadline_success_fraction':sum(e.remaining<=.01 for e in station.vehicles)/len(station.vehicles),
                       'energy_fulfillment_fraction':sum(e.delivered_kwh for e in station.vehicles)/required,
                       'unmet_energy_kwh':sum(e.remaining for e in station.vehicles),
                       'peak_site_kw':peak,'capacity_violation_samples':violations,
                       'socket_switches':switches,'rapid_switches':rapid,
                       'mean_local_decision_ms':sum(latencies)/len(latencies)}
    report={'scenario':'feasible low-energy requests' if feasible else 'congested original requests',
            'definition':'Same six-EV scenario and initial state for each model; 185 steps; timing excludes MQTT/Node-RED. Full network timing is in live_check.json.',
            'results':results}
    filename = 'control_feasible.json' if feasible else 'control_comparison.json'
    (ARTIFACTS/filename).write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    print(json.dumps(evaluate(),indent=2))
    print(json.dumps(evaluate(feasible=True),indent=2))
