"""Paired deterministic tariff demo; no MQTT publications or production DB writes."""
import json
from pathlib import Path
from station_core import schedule, tou_demo_station
from tou_scheduler import apply_tou, CONTROL_HOURS
from tariff import price_at


def evaluate():
    results = {}
    for policy in ('unmanaged', 'edf', 'tou'):
        station = tou_demo_station(unmanaged=policy == 'unmanaged')
        previous = None
        cost = energy = peak = 0.
        fallback = 0
        samples = []
        for step in range(240):
            station.hour = 16 + step * CONTROL_HOURS  # Avoid accumulated clock roundoff.
            state = station.snapshot()
            plan = schedule(state, {'profile_kwh': [0.] * 24})
            if policy == 'tou':
                plan = apply_tou(state, plan, previous)
                fallback += plan['tou_status'] == 'fallback_edf'
            if not station.accept(plan):
                raise AssertionError('Actuator rejected demo plan')
            before = sum(e.delivered_kwh for e in station.vehicles)
            station.step(CONTROL_HOURS)
            delivered = sum(e.delivered_kwh for e in station.vehicles) - before
            price = price_at(state['hour'])
            cost += delivered * price
            energy += delivered
            load = station.base_kw + delivered / CONTROL_HOURS
            peak = max(peak, load)
            samples.append({'hour': state['hour'], 'grid_kw': load, 'price_per_kwh': price})
            previous = plan
        results[policy] = dict(charging_cost_inr=round(cost, 4), delivered_kwh=round(energy, 6),
            peak_grid_kw=round(peak, 4), unmet_kwh=round(sum(e.remaining for e in station.vehicles), 6),
            deadlines_met=all(e.remaining <= .01 for e in station.vehicles),
            fallback_cycles=fallback, samples=samples)
    return {'scenario': 'Identical 4 kWh urgent and 12 kWh flexible requests, 16:00–24:00',
            'reference': 'Unmanaged removes the site limit for a counterfactual demand trace; same EVs, sockets, taper and deadlines.',
            'billing': 'EV energy only; fixed base load excluded from all three policies.',
            'results': results}


if __name__ == '__main__':
    report = evaluate()
    target = Path(__file__).with_name('artifacts') / 'tou_comparison.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: {m: v for m, v in r.items() if m != 'samples'}
                      for k, r in report['results'].items()}, indent=2))
