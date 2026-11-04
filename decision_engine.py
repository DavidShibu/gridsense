"""Performance-gated forecast plus dwell time and power deadband."""
import json
import math
import pickle
import time
from pathlib import Path
from station_core import schedule, site_limit_kw, edf_key
from tou_scheduler import apply_tou
from station_store import DB, database, read_state

_cache = {}


def load_bundle(path):
    path = Path(path).resolve()
    key = str(path)
    if key not in _cache:
        # Only load locally trained, trusted artifacts; pickle is not a data interchange format.
        bundle = pickle.loads(path.read_bytes()) if path.exists() else None
        if bundle:
            from ml_train import predict
            predict(bundle, 0)  # Warm imports, transforms and model before serving traffic.
        _cache[key] = bundle
    return _cache[key]


def initialize_models():
    """Call before binding HTTP port. New artifacts require a service restart."""
    return load_bundle(Path(__file__).with_name('artifacts')/'bundle.pkl')


def stabilize(state, plan, previous):
    """Hold valid occupants for >=6 simulated minutes; safety events may override.

    Preserve a socket for a continuing EV even after dwell expires. Rates within
    0.25 kW of the previous plan are held unless capacity/target changes demand it.
    """
    previous = previous or {}
    now = state['hour']
    active = {e['id']:e for e in state['vehicles'] if e['arrival'] <= now < e['departure'] and e['remaining_kwh'] > 1e-8}
    previous_assignments = {a['ev_id']:a for a in previous.get('assignments',[])}
    since = previous.get('assigned_since',{})
    chosen = []
    for a in previous.get('assignments',[]):
        if a['ev_id'] in active and now-since.get(a['ev_id'],now) < .1-1e-9:
            chosen.append(a['ev_id'])
    for a in plan['assignments']:
        if a['ev_id'] not in chosen and len(chosen) < len(state['chargers']):
            chosen.append(a['ev_id'])
    chosen.sort(key=lambda eid: edf_key(active[eid], now))
    # Existing assignments keep their physical socket; fill vacancies afterwards.
    sockets = {eid:previous_assignments[eid]['charger_id'] for eid in chosen if eid in previous_assignments}
    free = [c for c in state['chargers'] if c not in sockets.values()]
    for eid in chosen:
        if eid not in sockets:
            sockets[eid] = free.pop(0)
    remaining = max(0,site_limit_kw(state)-state['base_kw'])
    assignments = []
    for eid in chosen:
        ev = active[eid]
        desired = min(ev['max_kw'], remaining)
        old = previous_assignments.get(eid,{}).get('rate_kw')
        if old is not None and abs(desired-old) < .25:
            desired = old
        rate = math.floor(max(0,min(desired,ev['max_kw'],remaining))*100)/100
        remaining -= rate
        assignments.append({'ev_id':eid,'charger_id':sockets[eid],'rate_kw':rate})
    # No redistribution after deadband: that used to undo held power rates.
    plan['assignments'] = assignments
    plan['assigned_since'] = {eid:since.get(eid,now) if eid in previous_assignments else now for eid in chosen}
    plan['stability_policy'] = {'minimum_dwell_sim_minutes':6,'rate_deadband_kw':.25,
                               'override':'completion, departure and electrical safety'}
    return plan


def decide(key, path=DB, bundle_path=None, tou_enabled=True):
    started = time.perf_counter()
    state = read_state(key,path)  # No runtime sensor stream is used as a training input.
    bundle_path = bundle_path or Path(__file__).with_name('artifacts')/'bundle.pkl'
    bundle = load_bundle(bundle_path)
    if bundle:
        from ml_train import predict
        forecast, latency = predict(bundle,state['hour'])
        baseline = bundle['baseline']
        evaluation = bundle['report']
        selection = evaluation['selected_model']
    else:
        forecast, baseline, latency = 0,0,0
        evaluation = {'models':{},'selected_model':'untrained_safe_rules'}
        selection = 'untrained_safe_rules'
    # Existing scheduler reads a profile; replace ONLY the next-hour forecast.
    profile = [baseline]*24
    profile[int(state['hour']+1)%24] = forecast
    plan = schedule(state,{'profile_kwh':profile})
    plan.update(model=selection,performance=evaluation,inference_ms=latency,
                forecast_next_hour_kwh=forecast,run_id=state['run_id'],sensor_timestamp=state.get('timestamp',0))
    if not bundle:
        plan['alerts'].append('Models not trained: using safe deadline rules. Replay history and run ml_train.py.')
    with database(path) as conn:
        row = conn.execute('SELECT decision FROM cycles WHERE run_id=? AND sequence<? AND decision IS NOT NULL ORDER BY sequence DESC LIMIT 1',
                           (key['run_id'],key['sequence'])).fetchone()
        previous = json.loads(row['decision']) if row else None
    plan = apply_tou(state, plan, previous, enabled=tou_enabled)
    # The legacy stabilizer reallocates full available power, undoing price deferral.
    # Use it only for the fallback policy; certified ToU rates must remain intact.
    if plan['tou_status'] in ('disabled', 'fallback_edf'):
        plan = stabilize(state,plan,previous)
    plan['decision_ms'] = (time.perf_counter()-started)*1000
    with database(path) as conn:
        conn.execute('UPDATE cycles SET decision=? WHERE run_id=? AND sequence=?',(json.dumps(plan),key['run_id'],key['sequence']))
    return {'state':state,'decision':plan}
